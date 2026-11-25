type Name = 'copy' | 'check' | 'retry' | 'sidebar' | 'new' | 'edit' | 'plus' | 'image' | 'download' | 'link' | 'ask' | 'trash' | 'user' | 'settings' | 'send' | 'stop' | 'close' | 'news' | 'document' | 'globe' | 'chevron' | 'ephemeral' | 'create' | 'imageAdd' | 'brush' | 'scissors';
export function Icon({name}: {name: Name}) {
  const paths = {
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    retry: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3A7 7 0 0 0 17.9 17"/></>,
    sidebar: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></>,
    new: <path d="M12 4H6a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-6M15 3l6 6M11 13l-1 4 4-1 8-8a2.1 2.1 0 0 0-3-3z"/>,
    edit: <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16zM13.5 6.5l4 4"/>,
    plus: <path d="M12 5v14M5 12h14"/>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-9 9"/></>,
    imageAdd: <><path d="M13 4H5.5A2.5 2.5 0 0 0 3 6.5v11A2.5 2.5 0 0 0 5.5 20h13a2.5 2.5 0 0 0 2.5-2.5V12"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-9 9M18 2v6M15 5h6"/></>,
    brush: <><path d="m9.1 11.9 8-8a2.85 2.85 0 1 1 4 4l-8 8.1"/><path d="M7.1 14.9c-1.7 0-3 1.4-3 3 0 1.4-2.5 1.6-2 2.1 1.1 1.1 2.5 2 4 2 2.2 0 4-1.8 4-4a3 3 0 0 0-3-3.1z"/></>,
    scissors: <><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></>,
    download: <path d="M12 4v11m-5-5 5 5 5-5M5 20h14"/>,
    link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>,
    ask: <><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z"/><path d="M10 8.6a2 2 0 1 1 2.9 1.8c-.6.3-.9.8-.9 1.4M12 13.6h.01"/></>,
    trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
    settings: <><path d="M4 7h6m4 0h6M4 17h10m4 0h2"/><circle cx="12" cy="7" r="2"/><circle cx="16" cy="17" r="2"/></>,
    send: <path d="M12 19V5m-6 6 6-6 6 6"/>,
    stop: <rect x="7" y="7" width="10" height="10" rx="1"/>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
    document: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></>,
    globe: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></>,
    chevron: <path d="m7 10 5 5 5-5"/>,
    create: <path d="m4 20 11-11 2 2L6 22zM17 3v4M15 5h4M20.5 10v3M19 11.5h3M10 3v2M9 4h2"/>,
    ephemeral: <path d="M12 4a8 8 0 1 1-4.2 14.8L4 20l1.2-3.7A8 8 0 0 1 12 4z" strokeDasharray="2.6 2.4"/>,
    news: <path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5l-1.9-5.7-5.6-1.9L10.1 9zM18.5 3v3.5M16.8 4.8h3.5"/>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}
