import copy
from dataclasses import replace
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image, ImageChops
from subtitle_app.models import CaptionStatus, CaptionRenderRequest, JobItemStatus, StyleSettings
from subtitle_app.native_security import NativeDropPaths, local_navigation
from subtitle_app.web_controller import WebController, fingerprint
from subtitle_app.web_fonts import font_entries
from subtitle_app.web_persistence import TrustedStore
from subtitle_app.web_server import AppServer
from subtitle_app.render_service import RenderService


class BoundaryIntegrationTests(unittest.TestCase):
    def test_preflight_measures_geometry_without_rendering_full_images(self):
        with patch.object(RenderService, "render", side_effect=AssertionError("Preflight must not rasterize")):
            result = self.call("preflight", {"outputToken": "out"})
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["errors"], result)

    def test_raw_thumbnail_reports_original_dimensions(self):
        asset = self.c.project.assets[0]
        reply = self.call("preview", {"assetId": asset.id, "projectId": self.c.project.id,
                                      "revision": self.c.project.revision, "size": 160, "raw": True})
        self.assertEqual((640, 360), (reply["result"]["width"], reply["result"]["height"]))
        with Image.open(io.BytesIO(self.c.media[reply["result"]["token"]])) as thumbnail:
            self.assertEqual(160, max(thumbnail.size))

    def test_export_checkpoints_recover_outputs_without_rewriting_full_manifest_per_image(self):
        with patch.object(self.c, "_save_manifest", wraps=self.c._save_manifest) as save:
            self.start()
            self.wait_job()
            self.assertEqual(2, save.call_count)
        # Recreate a crash boundary: base manifest is still pending, item checkpoints
        # and atomically published files survived. No source or output is overwritten.
        import hashlib
        name = f"job-{hashlib.sha256(self.c.project.id.encode()).hexdigest()}.json"
        base = self.c.trusted.load(name)
        base["state"] = "running"
        for item in base["items"]:
            item["status"] = "pending"
            item["output_fingerprint"] = None
        self.c.trusted.save(name, base)
        restarted = WebController(self.root / "data")
        restarted.open_project(self.c.project_path)
        self.assertEqual("complete", restarted.job["state"])
        self.assertTrue(all(i.status == JobItemStatus.SUCCESS for i in restarted.job["items"]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.files = [self.source / f'字幕{i}.png' for i in range(3)]
        for path in self.files:
            Image.new('RGB', (640, 360), 'white').save(path)
        self.c = WebController(self.root / 'data')
        self.c.import_paths(self.files)
        for asset in self.c.project.assets:
            self.call('caption_style', {'assetId': asset.id, 'captionId': asset.subtitles[0].id, 'style': {'font_size': 24}})
            self.call('confirm', {'assetId': asset.id})
        self.c.outputs['out'] = self.root / 'out'

    def tearDown(self):
        deadline = time.monotonic() + 10
        while self.c.running and time.monotonic() < deadline:
            time.sleep(.01)
        self.settle()
        self.temp.cleanup()

    def settle(self):
        # The export thread marks the job finished and then writes its manifest while holding the lock;
        # taking the lock waits for that write (Windows cannot delete a file that is still open).
        with self.c.lock:
            pass

    def call(self, action, payload=None):
        p = self.c.project
        return self.c.dispatch({'action': action, 'payload': payload or {}, 'projectId': p.id, 'expectedRevision': p.revision, 'requestId': uuid4().hex})

    def start(self, **options):
        result = self.call('preflight', {'outputToken': 'out', **options})
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['result']['errors'], result)
        result = self.call('start_export', {'preflightId': result['result']['id'], 'acknowledge': True})
        self.assertTrue(result['ok'], result)

    def wait_job(self):
        deadline = time.monotonic() + 10
        while self.c.running and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.c.running)
        self.settle()

    def test_selected_export_does_not_include_others(self):
        self.start(assetIds=[self.c.project.assets[1].id], format='png')
        self.wait_job()
        self.assertEqual('complete', self.c.job['state'])
        self.assertEqual([self.files[1].name], [p.name for p in (self.root / 'out').iterdir()])

    def test_empty_export_scope_is_not_all(self):
        result = self.call('preflight', {'outputToken': 'out', 'assetIds': []})
        self.assertEqual('EMPTY_SCOPE', result['error']['code'])

    def test_reveal_source_resolves_only_authorized_asset(self):
        calls = []
        self.c.native = lambda action, payload: calls.append((action, payload))
        asset = self.c.project.assets[0]
        result = self.call('open_source', {'assetId': asset.id, 'path': '/etc/passwd'})
        self.assertTrue(result['ok'], result)
        self.assertEqual([('open_source', {'path': str(self.files[0].resolve())})], calls)
        self.c.grants.clear()
        denied = self.call('open_source', {'assetId': asset.id})
        self.assertFalse(denied['ok'])
        self.assertEqual(1, len(calls))

    def test_grants_survive_restart_but_untrusted_json_cannot_add_one(self):
        restarted = WebController(self.root / 'data')
        restarted.open_project(self.c.project_path)
        self.assertTrue(restarted._authorized(self.files[0]))
        value = json.loads((self.root / 'data/grants.json').read_text())
        value['payload'] = json.dumps(['/etc/passwd'])
        (self.root / 'data/grants.json').write_text(json.dumps(value))
        self.assertFalse(WebController(self.root / 'data').grants)

    def test_stop_finishes_current_then_retry_skips_success(self):
        original = RenderService.render
        started = threading.Event()
        release = threading.Event()
        def slow(renderer, *args, **kwargs):
            if threading.current_thread().name == 'subtitle-export':
                started.set(); release.wait(5)
            return original(renderer, *args, **kwargs)
        with patch.object(RenderService, 'render', slow):
            self.start()
            self.assertTrue(started.wait(5))
            self.call('stop_export', {'jobId': self.c.job['id']})
            release.set(); self.wait_job()
        self.assertEqual('stopped', self.c.job['state'])
        self.assertEqual(1, sum(i.status == JobItemStatus.SUCCESS for i in self.c.job['items']))
        first = self.c.job['items'][0].output_path
        original_time = first.stat().st_mtime_ns
        self.assertTrue(self.call('retry_export', {'jobId': self.c.job['id']})['ok'])
        self.wait_job()
        self.assertEqual('complete', self.c.job['state'])
        self.assertEqual(original_time, first.stat().st_mtime_ns)

    def test_stopping_during_the_last_image_still_completes(self):
        # Stopping finishes the current image; when that was the last one, nothing is left undone.
        original = RenderService.render
        started = threading.Event()
        release = threading.Event()
        def slow(renderer, *args, **kwargs):
            if threading.current_thread().name == 'subtitle-export':
                started.set(); release.wait(5)
            return original(renderer, *args, **kwargs)
        with patch.object(RenderService, 'render', slow):
            self.start(assetIds=[self.c.project.assets[0].id])
            self.assertTrue(started.wait(5))
            self.call('stop_export', {'jobId': self.c.job['id']})
            release.set(); self.wait_job()
        self.assertEqual('complete', self.c.job['state'])

    def test_an_animation_says_only_its_first_frame_is_exported(self):
        frames = [Image.new('RGB', (640, 360), color) for color in ('white', 'gray')]
        frames[0].save(self.files[2], save_all=True, append_images=frames[1:], duration=100)
        check = self.call('preflight', {'outputToken': 'out'})['result']
        cards = [w for w in check['warnings'] if '动图' in w['message']]
        self.assertEqual([[self.c.project.assets[2].id]], [w['assetIds'] for w in cards])
        self.assertEqual(3, check['count'])

    def test_restart_recovers_job_without_trusting_project_manifest(self):
        self.start(); self.wait_job()
        first = self.c.job['items'][0]
        # Simulate crash after atomic publication, before success acknowledgement.
        first.status = JobItemStatus.RUNNING
        self.c.job['state'] = 'running'
        self.c._save_manifest()
        self.c.job['state'] = 'complete'
        restarted = WebController(self.root / 'data')
        restarted.open_project(self.c.project_path)
        self.assertEqual('complete', restarted.job['state'])
        self.assertTrue(all(i.status == JobItemStatus.SUCCESS for i in restarted.job['items']))

    def test_changed_source_rejects_resume(self):
        self.start(); self.wait_job()
        item = self.c.job['items'][0]
        item.output_path.unlink()
        item.status = JobItemStatus.FAILED
        Image.new('RGB', (640, 360), 'black').save(item.source_path)
        self.assertEqual('SOURCE_CHANGED', self.call('retry_export', {'jobId': self.c.job['id']})['error']['code'])

    def test_output_preview_is_actual_export_and_protected_by_job(self):
        self.start(); self.wait_job()
        result = self.call('output_preview', {'jobId': self.c.job['id'], 'index': 0})
        self.assertTrue(result['ok'])
        self.assertIn(result['result']['token'], self.c.media)
        self.assertFalse(self.call('output_preview', {'jobId': 'forged', 'index': 0})['ok'])

    def test_backup_recovery_never_overwrites_broken_original(self):
        original = self.c.project_path
        original.write_bytes(b'{broken')
        self.assertEqual('BACKUP_AVAILABLE', self.call('open_recent', {'index': 0})['error']['code'])
        self.assertTrue(self.call('recover_project')['ok'])
        self.assertEqual(b'{broken', original.read_bytes())
        self.assertNotEqual(original, self.c.project_path)

    def test_detection_toggle_does_not_move_caption(self):
        asset = self.c.project.assets[0]
        before = copy.deepcopy(self.c.project)
        with patch('subtitle_app.web_controller.LayoutService.detect_protected_regions', return_value=[]):
            self.assertTrue(self.call('detect_regions', {'assetId': asset.id})['ok'])
        self.assertEqual(before, self.c.project)

    def test_drop_requires_native_stage_and_keeps_explicit_scope(self):
        self.assertFalse(self.call('accept_drop', {'dropId': 'forged', 'paths': ['/etc/passwd']})['ok'])
        self.c.stage_drop([self.files[0]])
        result = self.call('accept_drop', {'dropId': self.c.pending_drop['id']})
        self.assertEqual(1, result['result']['duplicates'])
        self.assertIsNone(self.c.pending_drop)

    def test_real_output_formats_keep_dimensions(self):
        for extension in ('png', 'jpg', 'webp', 'bmp'):
            with self.subTest(extension=extension):
                self.c.outputs['out'] = self.root / extension
                self.start(format=extension, assetIds=[self.c.project.assets[0].id])
                self.wait_job()
                self.assertEqual('complete', self.c.job['state'])
                with Image.open(self.c.job['items'][0].output_path) as image:
                    self.assertEqual((640, 360), image.size)

    def test_editable_preview_contains_real_raster_layers(self):
        asset = self.c.project.assets[0]
        result = self.call('preview', {'assetId': asset.id, 'projectId': self.c.project.id, 'revision': self.c.project.revision, 'size': 640, 'editable': True})
        self.assertTrue(result['ok'], result)
        preview = result['result']
        with Image.open(io.BytesIO(self.c.media[preview['backgroundToken']])) as original:
            combined = original.convert('RGBA')
        for overlay in preview['overlays']:
            with Image.open(io.BytesIO(self.c.media[overlay['layerToken']])) as layer:
                combined.alpha_composite(layer.convert('RGBA'), tuple(overlay['bounds'][:2]))
        with Image.open(io.BytesIO(self.c.media[preview['token']])) as rendered:
            self.assertIsNone(ImageChops.difference(combined, rendered).getbbox())

    def test_builtin_preset_changes_look_but_keeps_layout_and_size(self):
        asset = self.c.project.assets[0]
        scope = {'assetId': asset.id, 'captionId': asset.subtitles[0].id}
        self.call('caption_style', {**scope, 'style': {'max_width': 0.3, 'alignment': 'left'}})
        self.assertTrue(self.call('apply_preset', {**scope, 'name': '柔和'})['ok'])
        style = self.c._style(self.c.project.assets[0].subtitles[0])
        self.assertEqual((0.3, 'left', 24, 0), (style['max_width'], style['alignment'], style['font_size'], style['stroke_width']))

    def test_bold_outline_preset_brings_its_font_slant_and_a_size_relative_outline(self):
        asset = self.c.project.assets[0]
        scope = {'assetId': asset.id, 'captionId': asset.subtitles[0].id}
        self.call('caption_style', {**scope, 'style': {'font_size': 100}})
        self.assertTrue(self.call('apply_preset', {**scope, 'name': '粗描边斜体'})['ok'])
        caption = self.c.snapshot()['project']['assets'][0]['captions'][0]['style']
        black = next(f for f in font_entries().values() if f['label'] == '思源黑体' and f['weight'] == 900)
        self.assertEqual((100, 20, 19.0, 900, black['id']), (caption['font_size'], caption['stroke_width'], caption['skew'], caption['font_weight'], caption['font_id']))

    def test_weight_and_slant_survive_saving_and_reopening_the_project(self):
        asset = self.c.project.assets[0]
        scope = {'assetId': asset.id, 'captionId': asset.subtitles[0].id}
        self.call('apply_preset', {**scope, 'name': '粗描边斜体'})
        self.call('caption_style', {**scope, 'style': {'skew': 12.5, 'letter_spacing': -3}})
        reopened = WebController(self.root / 'data')
        reopened.open_project(self.c.project_path)
        style = reopened._style(reopened.project.assets[0].subtitles[0])
        self.assertEqual((900, 12.5, -3), (style['font_weight'], style['skew'], style['letter_spacing']))

    def test_snapshot_lists_builtin_presets_with_their_fonts(self):
        cards = {card['name']: card for card in self.c.snapshot()['builtinPresets']}
        self.assertEqual(['经典', '柔和', '强调'], list(cards)[:3])
        self.assertEqual('思源黑体', cards['粗描边斜体']['fontLabel'])
        self.assertEqual(0.195, cards['粗描边斜体']['strokeRatio'])
        self.assertIsNone(cards['经典']['fontId'])

    def test_a_saved_preset_cannot_take_a_builtin_name(self):
        asset = self.c.project.assets[0]
        reply = self.call('preset', {'operation': 'save', 'name': '经典', 'assetId': asset.id, 'captionId': asset.subtitles[0].id})
        self.assertFalse(reply['ok'])
        self.assertEqual('PRESET_EXISTS', reply['error']['code'])

    def test_unconfirmed_images_are_one_warning_and_do_not_block(self):
        # 1000 images cannot all be confirmed by hand: review is optional, export follows the current text.
        for asset in self.c.project.assets[:2]:
            self.call('caption_text', {'assetId': asset.id, 'captionId': asset.subtitles[0].id, 'text': '改过的字幕'})
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        unconfirmed = [w for w in check['warnings'] if w.get('action') == 'confirm']
        self.assertEqual([2], [len(w['assetIds']) for w in unconfirmed])
        self.assertIn('还没确认', unconfirmed[0]['message'])
        self.assertTrue(self.call('start_export', {'preflightId': check['id'], 'acknowledge': True})['ok'])
        self.wait_job()
        self.assertEqual('complete', self.c.job['state'])

    def test_images_without_captions_are_one_warning_and_export_as_the_original(self):
        asset = self.c.project.assets[0]
        self.call('caption_delete', {'assetId': asset.id, 'captionId': asset.subtitles[0].id})
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        missing = [w for w in check['warnings'] if w.get('action') == 'no_caption']
        self.assertEqual([[asset.id]], [w['assetIds'] for w in missing])
        self.assertIn('按原图导出', missing[0]['message'])
        self.assertEqual(3, check['count'])
        skipped = self.call('preflight', {'outputToken': 'out', 'includeNoCaption': False})['result']
        self.assertIn('不会导出', [w for w in skipped['warnings'] if w.get('action') == 'no_caption'][0]['message'])
        self.assertEqual(2, skipped['count'])

    def test_an_empty_caption_is_a_warning_not_a_box(self):
        asset = self.c.project.assets[0]
        self.call('caption_add', {'assetId': asset.id})
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual([[asset.id]], [w['assetIds'] for w in check['warnings'] if '空字幕' in w['message']])

    def left_out(self, check, text):
        """The ids on the card for images left out of the export for this reason."""
        cards = [w for w in check['warnings'] if text in w['message'] and '不会导出' in w['message']]
        self.assertEqual(1, len(cards), check['warnings'])
        self.assertEqual('resolve', cards[0].get('action'))
        return cards[0]['assetIds']

    def test_a_broken_image_is_left_out_and_the_rest_export(self):
        # One broken file must not hold back the rest (2026-11-13).
        broken = self.c.project.assets[1]
        self.files[1].write_bytes(b'not an image')
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual([broken.id], self.left_out(check, '无法读取'))
        self.assertEqual(2, check['count'])
        self.assertTrue(self.call('start_export', {'preflightId': check['id'], 'acknowledge': True})['ok'])
        self.wait_job()
        self.assertEqual('complete', self.c.job['state'])
        self.assertEqual(sorted([self.files[0].name, self.files[2].name]), sorted(p.name for p in (self.root / 'out').iterdir()))

    def test_a_missing_source_is_left_out(self):
        missing = self.c.project.assets[0]
        self.files[0].unlink()
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual([missing.id], self.left_out(check, '找不到源文件'))
        self.assertEqual(2, check['count'])

    def test_an_overflowing_caption_is_left_out_without_a_gap_in_the_numbers(self):
        big = self.c.project.assets[1]
        self.call('caption_style', {'assetId': big.id, 'captionId': big.subtitles[0].id, 'style': {'safe_edge': False}})
        self.call('caption_position', {'assetId': big.id, 'captionId': big.subtitles[0].id, 'x': 0.99, 'y': 0.5})
        check = self.call('preflight', {'outputToken': 'out', 'naming': 'sequence'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual([big.id], self.left_out(check, '超出画面'))
        self.assertEqual(['01.png', '02.png'], check['files'])
        self.assertEqual([a.id for a in self.c.project.assets if a.id != big.id], [o['assetId'] for o in check['outputs']])

    def test_an_unavailable_font_is_left_out_and_never_opened(self):
        odd = self.c.project.assets[2]
        odd.subtitles[0].style_overrides['font_path'] = str(self.root / '不存在.ttf')
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual([odd.id], self.left_out(check, '字体不可用'))
        self.assertNotIn(odd.id, [o['assetId'] for o in check['outputs']])

    def test_missing_glyphs_count_the_speaker_prefix_too(self):
        plain, spoken = self.c.project.assets[0], self.c.project.assets[1]
        self.call('caption_text', {'assetId': plain.id, 'captionId': plain.subtitles[0].id, 'text': '缺字'})
        self.call('caption_speaker', {'assetId': spoken.id, 'captionId': spoken.subtitles[0].id, 'speaker': '鬼'})
        self.call('project_settings', {'showSpeaker': True})
        drawable = frozenset(map(ord, '字幕0123456789'))
        with patch('subtitle_app.web_controller.font_codepoints', return_value=drawable):
            check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertEqual([], check['errors'])
        self.assertEqual(sorted([plain.id, spoken.id]), sorted(self.left_out(check, '缺少字形')))
        self.assertEqual(1, check['count'])

    def test_a_name_windows_refuses_is_left_out(self):
        check = self.call('preflight', {'outputToken': 'out', 'prefix': '问?'})['result']
        self.assertEqual(3, len(self.left_out(check, 'Windows 上不可用')))
        self.assertIn('没有可导出的图片', [e['message'] for e in check['errors']])

    def test_keeping_the_format_ignores_the_hidden_quality(self):
        # 保持原格式 hides the quality slider; a value left at 10 from JPEG used to apply anyway.
        self.call('preflight', {'outputToken': 'out', 'format': 'original', 'quality': 10})
        self.assertEqual({None}, {item.quality for item in self.c.preflight['plan'].items})
        self.call('preflight', {'outputToken': 'out', 'format': 'jpg', 'quality': 10})
        self.assertEqual({10}, {item.quality for item in self.c.preflight['plan'].items})

    def test_a_source_removed_after_the_check_fails_only_that_image(self):
        check = self.call('preflight', {'outputToken': 'out', 'format': 'png'})['result']
        self.files[1].unlink()
        self.assertTrue(self.call('start_export', {'preflightId': check['id'], 'acknowledge': True})['ok'])
        self.wait_job()
        self.assertEqual(['success', 'failed', 'success'], [i.status.value for i in self.c.job['items']])
        self.assertEqual('找不到源图片', self.c.job['items'][1].error_message)

    @unittest.skipIf(os.name == 'nt', 'Windows ignores read-only folders')
    def test_failed_files_say_why_in_plain_words(self):
        check = self.call('preflight', {'outputToken': 'out', 'format': 'png'})['result']
        out = self.root / 'out'
        out.mkdir()
        out.chmod(0o555)
        try:
            self.call('start_export', {'preflightId': check['id'], 'acknowledge': True})
            self.wait_job()
        finally:
            out.chmod(0o755)
        messages = {i.error_message for i in self.c.job['items']}
        self.assertEqual({'没有权限写入保存位置'}, messages)

    def test_a_check_cannot_start_an_export_in_another_project(self):
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.c.project = replace(self.c.project, id='另一个项目')
        reply = self.call('start_export', {'preflightId': check['id'], 'acknowledge': True})
        self.assertEqual('PREFLIGHT_EXPIRED', reply['error']['code'])

    @unittest.skipIf(os.name == 'nt', 'NTFS counts 255 characters, not bytes')
    def test_a_name_longer_than_the_disk_allows_is_left_out(self):
        check = self.call('preflight', {'outputToken': 'out', 'prefix': '长' * 85})['result']
        self.assertEqual(3, len(self.left_out(check, '文件名')))

    def test_exporting_again_into_the_same_folder_is_one_card(self):
        self.start(format='png')
        self.wait_job()
        check = self.call('preflight', {'outputToken': 'out', 'format': 'png'})['result']
        self.assertEqual([], [w for w in check['warnings'] if '已存在' in w['message']])
        renamed = [w['message'] for w in check['warnings'] if '同名' in w['message']]
        self.assertEqual(1, len(renamed), check['warnings'])
        self.assertIn('3 个', renamed[0])
        self.assertTrue(all(name.endswith('_2.png') for name in check['files']))

    def test_captions_without_a_place_stack_in_reading_order(self):
        # The first caption on top, as 智能避让 places them; a dialogue used to read upwards (2026-11-13).
        asset = self.c.project.assets[0]
        added = self.call('caption_add', {'assetId': asset.id})['result']['captionId']
        self.call('caption_text', {'assetId': asset.id, 'captionId': added, 'text': '第二条'})
        shown = next(a for a in self.call('state')['result']['project']['assets'] if a['id'] == asset.id)
        self.assertEqual([0.74, 0.86], [round(c['position'][1], 2) for c in shown['captions']])
        self.call('preflight', {'outputToken': 'out'})
        exported = self.c.preflight['plan'].items[0].captions
        self.assertEqual([0.74, 0.86], [round(c.position_ratio[1], 2) for c in exported])

    def test_a_broken_image_preview_says_so_in_plain_words(self):
        asset = self.c.project.assets[0]
        self.files[0].write_bytes(b'not an image')
        for mode in ({'raw': True}, {'editable': True, 'layersOnly': True}):
            reply = self.call('preview', {'assetId': asset.id, 'projectId': self.c.project.id, 'revision': self.c.project.revision, 'size': 160, **mode})
            self.assertEqual('SOURCE_UNREADABLE', reply['error']['code'], reply)
            self.assertNotIn(str(self.root), reply['error']['message'])

    def test_nothing_left_to_export_is_an_error(self):
        for path in self.files:
            path.unlink()
        check = self.call('preflight', {'outputToken': 'out'})['result']
        self.assertIn('没有可导出的图片', [e['message'] for e in check['errors']])
        self.assertEqual(3, len(self.left_out(check, '找不到源文件')))

    def test_preview_renders_unsaved_text_without_writing_project(self):
        asset = self.c.project.assets[0]
        caption = asset.subtitles[0]
        def layer_width(**extra):
            reply = self.call('preview', {'assetId': asset.id, 'projectId': self.c.project.id, 'revision': self.c.project.revision, 'size': 640, 'editable': True, 'layersOnly': True, **extra})
            return reply['result']['overlays'][0]['renderWidth']
        saved, revision = caption.text, self.c.project.revision
        self.assertGreater(layer_width(texts={caption.id: saved * 3}), layer_width())
        self.assertEqual((saved, revision), (self.c.project.assets[0].subtitles[0].text, self.c.project.revision))
        self.assertFalse(self.call('preview', {'assetId': asset.id, 'projectId': self.c.project.id, 'revision': revision, 'editable': True, 'texts': {'missing': 'x'}})['ok'])

    def test_editor_background_is_jpeg_only_when_opaque(self):
        asset = self.c.project.assets[0]
        def background():
            reply = self.call('preview', {'assetId': asset.id, 'projectId': self.c.project.id, 'revision': self.c.project.revision, 'size': 640, 'editable': True, 'layersOnly': True})
            return Image.open(io.BytesIO(self.c.media[reply['result']['backgroundToken']])).format
        self.assertEqual('JPEG', background())
        Image.new('RGBA', (640, 360), (255, 255, 255, 0)).save(asset.source_path)
        self.assertEqual('PNG', background())

    def test_batch_position_reports_different_aspect_before_applying(self):
        source, target = self.c.project.assets[:2]
        Image.new('RGB', (360, 640), 'white').save(target.source_path)
        payload = {'assetId': source.id, 'captionId': source.subtitles[0].id, 'assetIds': [source.id, target.id], 'style': False, 'position': True}
        before = copy.deepcopy(self.c.project)
        result = self.call('batch_style_preview', payload)
        self.assertEqual([target.id], result['result']['differentAspect'])
        self.assertEqual(before, self.c.project)
        result = self.call('batch_style_preview', {**payload, 'sameAspect': True})
        self.assertEqual([], result['result']['updated'])

    def test_each_project_keeps_its_own_export_recovery_record(self):
        self.start(); self.wait_job()
        first_project = self.c.project_path
        first_job = self.c.job['id']
        self.call('new_project', {'name': 'Second project'})
        self.c.import_paths([self.files[0]])
        asset = self.c.project.assets[0]
        self.call('caption_style', {'assetId': asset.id, 'captionId': asset.subtitles[0].id, 'style': {'font_size': 24}})
        self.call('confirm', {'assetId': asset.id})
        self.c.outputs['out'] = self.root / 'second-out'
        self.start(); self.wait_job()
        restarted = WebController(self.root / 'data')
        restarted.open_project(first_project)
        self.assertEqual(first_job, restarted.job['id'])

    def test_failed_project_save_does_not_leave_temporary_file(self):
        folder = self.c.project_path.parent
        with patch('subtitle_app.project_store.os.replace', side_effect=OSError('disk full')):
            result = self.call('rename', {'name': 'Must not commit'})
        self.assertFalse(result['ok'])
        self.assertEqual([], list(folder.glob('.*.tmp')))
        self.assertNotEqual('Must not commit', self.c.project.name)

    def test_recent_thumbnail_is_read_only_and_scoped_to_known_projects(self):
        before = copy.deepcopy(self.c.project)
        self.assertTrue(self.call('recent_preview', {'path': str(self.c.project_path)})['ok'])
        self.assertFalse(self.call('recent_preview', {'path': '/etc/passwd'})['ok'])
        self.assertEqual(before, self.c.project)

    def test_page_resume_does_not_pollute_undo_or_export_revision(self):
        revision, undo = self.c.project.revision, len(self.c.undo)
        self.assertTrue(self.call('view_page', {'page': 'editor'})['ok'])
        self.assertEqual(revision, self.c.project.revision)
        self.assertEqual(undo, len(self.c.undo))
        restarted = WebController(self.root / 'data')
        self.assertEqual('editor', restarted.open_project(self.c.project_path)['page'])


class SecurityAndLayoutTests(unittest.TestCase):
    def test_native_navigation_rejects_remote_file_and_authority_confusion(self):
        origin = 'http://127.0.0.1:19001/'
        self.assertTrue(local_navigation(origin + '#section', origin))
        for url in ('https://example.com', 'file:///etc/passwd', 'http://127.0.0.1:19002/', 'http://127.0.0.1:19001@evil.com', origin + 'media/a', 'javascript:alert(1)'):
            self.assertFalse(local_navigation(url, origin), url)

    def test_fake_drop_path_never_receives_native_grant(self):
        paths = NativeDropPaths()
        event = {'dataTransfer': {'files': [{'pywebviewFullPath': '/tmp/example.png'}]}}
        self.assertEqual([], paths.consume(event))
        paths += [('example.png', '/tmp/example.png')]
        self.assertEqual([Path('/tmp/example.png').resolve()], paths.consume(event))
        self.assertEqual([], paths.consume(event))

    def test_rotated_caption_and_background_respect_edges(self):
        geometry = []
        style = StyleSettings(font_size=32, show_background=True)
        RenderService().render(Image.new('RGB', (640, 360)), [CaptionRenderRequest('Caption', (.99, .99), 45, style)], style, geometry=geometry)
        self.assertFalse(geometry[0]['overflow'])

    def test_large_caption_is_reported_not_silently_clipped(self):
        geometry = []
        style = StyleSettings(font_size=100)
        RenderService().render(Image.new('RGB', (200, 100)), [CaptionRenderRequest('Many words that cannot fit in this tiny image', (.5, .5), 0, style)], style, geometry=geometry)
        self.assertTrue(geometry[0]['overflow'])

    def test_letter_spacing_and_alignment_affect_shared_renderer(self):
        source = Image.new('RGB', (640, 360), 'white')
        style = StyleSettings(font_size=32, letter_spacing=8, alignment='left')
        a = RenderService().render(source, [CaptionRenderRequest('AVAV\nA', (.5, .5))], style)
        style = replace(style, alignment='right')
        b = RenderService().render(source, [CaptionRenderRequest('AVAV\nA', (.5, .5))], style)
        self.assertIsNotNone(ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getbbox())


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.front = self.root / 'frontend'; self.front.mkdir()
        (self.front / 'index.html').write_text('<html>local</html>')
        self.c = WebController(self.root / 'data')
        self.server = AppServer(self.c, self.front)
        self.server.start()

    def tearDown(self):
        self.server.stop(); self.temp.cleanup()

    def send(self, method='POST', path='/api', **headers):
        connection = http.client.HTTPConnection(self.server.authority, timeout=3)
        payload = json.dumps({'action': 'state'}) if method == 'POST' else None
        defaults = {'Content-Type': 'application/json', 'X-Jian-Token': self.server.token, 'Origin': self.server.origin, **headers}
        connection.request(method, path, body=payload, headers=defaults)
        response = connection.getresponse(); body = response.read(); received = dict(response.getheaders())
        code = response.status; connection.close()
        return code, received, body

    def test_session_token_origin_and_host_are_required(self):
        self.assertEqual(200, self.send()[0])
        self.assertEqual(403, self.send(**{'X-Jian-Token': 'wrong'})[0])
        self.assertEqual(403, self.send(Origin='https://evil.test')[0])
        self.assertEqual(403, self.send(Host='evil.test')[0])

    def test_static_paths_are_allowlisted(self):
        for path in ('/../data/state.key', '/%2e%2e/data/state.key', '/etc/passwd', '/node_modules/react/index.js'):
            self.assertEqual(404, self.send('GET', path)[0])

    def test_csp_has_no_remote_script_or_eval_permission(self):
        code, headers, body = self.send('GET', '/')
        self.assertEqual(200, code)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertNotIn('unsafe-eval', headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_media_requires_session(self):
        self.c.media['test'] = b'png'
        self.assertEqual(403, self.send('GET', '/media/test', **{'X-Jian-Token': ''})[0])
        self.assertEqual(200, self.send('GET', '/media/test')[0])

    def test_caption_font_requires_session(self):
        from subtitle_app.web_fonts import default_font_id
        self.assertEqual(403, self.send('GET', f'/caption-fonts/{default_font_id()}', **{'X-Jian-Token': ''})[0])

    def test_caption_font_serves_bundled(self):
        from subtitle_app.web_fonts import default_font_id, font_entries
        font = default_font_id()
        code, headers, body = self.send('GET', f'/caption-fonts/{font}')
        self.assertEqual(200, code)
        self.assertEqual(Path(font_entries()[font]['path']).read_bytes(), body)
        self.assertIn(headers['Content-Type'], ('font/ttf', 'font/otf'))

    def test_caption_font_rejects_unknown(self):
        from subtitle_app.web_fonts import font_entries
        system = next((key for key, font in font_entries().items() if not font['bundled']), None)
        for path in ('/caption-fonts/..%2Fapp.js', '/caption-fonts/nope', *((f'/caption-fonts/{system}',) if system else ())):
            with self.subTest(path=path):
                self.assertEqual(404, self.send('GET', path)[0])


if __name__ == '__main__':
    unittest.main()
