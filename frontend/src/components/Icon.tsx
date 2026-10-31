type Name = 'copy' | 'check' | 'retry' | 'sidebar' | 'new' | 'edit' | 'trash' | 'user' | 'settings' | 'send' | 'stop' | 'close';
export function Icon({name}: {name: Name}) {
  const paths = {
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    retry: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3A7 7 0 0 0 17.9 17"/></>,
    sidebar: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></>,
    new: <path d="M12 4H6a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-6M15 3l6 6M11 13l-1 4 4-1 8-8a2.1 2.1 0 0 0-3-3z"/>,
    edit: <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16zM13.5 6.5l4 4"/>,
    trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
    settings: <><path d="M4 7h6m4 0h6M4 17h10m4 0h2"/><circle cx="12" cy="7" r="2"/><circle cx="16" cy="17" r="2"/></>,
    send: <path d="M12 19V5m-6 6 6-6 6 6"/>,
    stop: <rect x="7" y="7" width="10" height="10" rx="1"/>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}
