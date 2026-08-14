const API = 'http://127.0.0.1:8000';

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'collect-word',
    title: '收藏单词',
    contexts: ['selection']
  });
});

function showToast(tabId, type, word, detail) {
  const bg = type === 'loading' ? '#007aff' : type === 'success' ? '#34c759' : '#ff3b30';
  const icon = type === 'loading' ? '⏳' : type === 'success' ? '✓' : '✕';
  const title = type === 'loading' ? '正在提交...' : type === 'success' ? '已收藏' : '收藏失败';
  const msg = type === 'loading'
    ? `「${word}」正在添加到词汇本`
    : type === 'success'
      ? `「${word}」已添加到词汇本`
      : (detail || '未知错误');

  chrome.scripting.executeScript({
    target: { tabId },
    func: (bg, icon, title, msg, keep) => {
      const existing = document.getElementById('__vocab_toast__');
      if (existing) {
        const iconEl = existing.querySelector('span');
        const titleEl = existing.querySelector('b');
        const msgEl = existing.querySelector('span:last-child');
        if (iconEl) iconEl.textContent = icon;
        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = msg;
        existing.style.background = bg;
        if (!keep) {
          setTimeout(() => {
            existing.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            existing.style.opacity = '0';
            existing.style.transform = 'translateX(20px)';
            setTimeout(() => { existing.remove(); }, 300);
          }, 2500);
        }
        return;
      }

      const toast = document.createElement('div');
      toast.id = '__vocab_toast__';
      toast.innerHTML = `<span style="font-size:18px;margin-right:8px">${icon}</span><div><b>${title}</b><br><span style="font-size:13px;opacity:0.9">${msg}</span></div>`;
      Object.assign(toast.style, {
        position: 'fixed',
        top: '20px',
        right: '20px',
        zIndex: '2147483647',
        background: bg,
        color: '#fff',
        padding: '14px 20px',
        borderRadius: '12px',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
        fontSize: '15px',
        fontWeight: '500',
        lineHeight: '1.4',
        display: 'flex',
        alignItems: 'center',
        boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
        animation: '__vocab_slide__ 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        pointerEvents: 'none'
      });

      const style = document.createElement('style');
      style.textContent = '@keyframes __vocab_slide__ { from { opacity:0; transform:translateX(20px) } to { opacity:1; transform:translateX(0) } }';
      document.head.appendChild(style);
      document.body.appendChild(toast);

      setTimeout(() => {
        toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => { toast.remove(); style.remove(); }, 300);
      }, 2500);
    },
    args: [bg, icon, title, msg, type === 'loading']
  }).catch(() => {});
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== 'collect-word' || !info.selectionText) return;

  const word = info.selectionText.trim();
  if (!word) return;

  showToast(tab.id, 'loading', word);

  try {
    const resp = await fetch(`${API}/api/words`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression: word, skip_spell_check: true })
    });

    if (resp.ok) {
      showToast(tab.id, 'success', word);
    } else {
      const err = await resp.json().catch(() => ({ detail: '请求失败' }));
      showToast(tab.id, 'error', word, err.detail);
    }
  } catch (e) {
    showToast(tab.id, 'error', word, '无法连接到后端，请确认 python main.py 已启动');
  }
});
