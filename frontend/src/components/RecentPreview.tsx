import { useEffect, useState } from 'react';
import { Folder } from 'lucide-react';
import { mediaUrl, request } from '../bridge';

export function RecentPreview({ path, updatedAt }: { path: string; updatedAt: string }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    let alive = true, allocated = '';
    request<{ token: string }>('recent_preview', { path }).then(async r => {
      const next = await mediaUrl(r.result.token);
      if (alive) { allocated = next; setUrl(next); } else URL.revokeObjectURL(next);
    }).catch(() => { if (alive) setUrl(''); });
    return () => { alive = false; if (allocated) URL.revokeObjectURL(allocated); };
  }, [path, updatedAt]);
  return <div className="image-preview recent-placeholder">{url ? <img src={url} alt="项目预览" /> : <Folder />}</div>;
}
