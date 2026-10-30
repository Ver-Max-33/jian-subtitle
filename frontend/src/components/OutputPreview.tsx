import { useEffect, useState } from 'react';
import { ImageOff } from 'lucide-react';
import { mediaUrl, request } from '../bridge';
import { useApp } from '../state';

export function OutputPreview({ jobId, index }: { jobId: string; index: number }) {
  const { state } = useApp();
  const filename = state?.job?.items.find(item => item.index === index)?.file || '';
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true, objectUrl = '';
    request<{ token: string }>('output_preview', { jobId, index }).then(async response => {
      objectUrl = await mediaUrl(response.result.token);
      if (alive) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl);
    }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [jobId, index]);
  return <figure className="output-thumb"><div className="image-preview">{url ? <img src={url} alt={`已导出图片：${filename}`} /> : failed ? <ImageOff aria-label="输出文件已移动或修改" /> : <span className="image-loading" />}</div><figcaption className="truncate" title={filename}>{filename}</figcaption></figure>;
}
