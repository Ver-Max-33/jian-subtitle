import { ChevronDown, Images, MoreHorizontal } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import { count, dayTime } from '../format';
import { AppMark, Button, Menu } from '../components/ui';
import { RecentPreview } from '../components/RecentPreview';
import { useAppMenu } from '../components/LeftPanel';

const resume: Record<string, string> = { editor: '继续编辑', export: '继续导出', review: '继续校对', import: '继续校对' };

export function Home({ dragging }: { dragging: boolean }) {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const menu = useAppMenu();
  if (!state) return null;
  const open = (action: string, payload: Record<string, unknown> = {}) => act(async () => { const r = await mutate<{ cancelled?: boolean }>(action, payload); if (!r?.cancelled) w.setPage('workspace'); });
  const recents = state.recents;
  return <div className="home">
    <header className="home-top"><Menu label="应用菜单" className="app-menu-trigger wide" items={menu}><AppMark /><strong>简幕</strong><ChevronDown /></Menu></header>
    <main className="home-main">
      <div className="home-heading"><h1>开始一组新字幕</h1><Button onClick={() => open('open_project')}>打开项目</Button></div>
      <section className={`drop-zone ${dragging ? 'dragging' : ''}`} aria-label="导入图片">
        <span className="drop-icon"><Images /></span>
        <h2>{dragging ? '松开即可导入' : '把图片或文件夹拖到这里'}</h2>
        <p>JPG、PNG、WebP、BMP · 文件名会识别为字幕，拍摄时间单独保留并用来排序</p>
        <div className="drop-actions"><Button variant="primary" onClick={() => w.openDialog('new-project', { importAction: 'choose_images' })}>选择图片</Button><Button onClick={() => w.openDialog('new-project', { importAction: 'choose_folder' })}>选择文件夹</Button></div>
      </section>
      {recents.length ? <>
        <div className="home-heading small"><h3>最近项目</h3>{recents.length > 4 && <button type="button" className="link" onClick={() => w.openDialog('recents')}>查看全部 {recents.length} 个</button>}</div>
        <section className="recent-grid">{recents.slice(0, 4).map(r => <article key={r.path} className="recent-card">
          <button type="button" className="recent-open" onClick={() => open('open_recent', { index: r.index })}>
            <RecentPreview path={r.path} updatedAt={r.updatedAt} />
            <span className="recent-name">{r.name}</span>
            <span className="recent-meta"><span className="numeric">{count(r.count)} 张 · {dayTime(r.updatedAt)}</span><span className="recent-action">{resume[r.page] ?? '继续编辑'}</span></span>
          </button>
          <Menu label={`${r.name} 的更多操作`} className="icon-button recent-more" align="end" items={[{ label: '移除记录…', action: () => w.openDialog('remove-recent', { path: r.path, name: r.name }) }]}><MoreHorizontal /></Menu>
        </article>)}</section>
      </> : <section className="first-run" aria-label="怎么开始">
        {[['1', '拖入图片', '截图、照片都可以；文件名就是字幕'], ['2', '逐张校对', '按拍摄时间排好，确认每张的文字'], ['3', '导出', '原尺寸带字幕导出，可以顺序命名']].map(([n, title, body]) => <div key={n} className="first-step"><span className="step-number">{n}</span><strong>{title}</strong><small>{body}</small></div>)}
      </section>}
    </main>
  </div>;
}
