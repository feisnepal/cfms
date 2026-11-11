import { useEffect } from 'react';

/** Set the tab title and the canonical link of the page while it is shown, then put them back. Search engines read the server-rendered copy; this keeps the app's own copy honest. */
export function useDocumentMeta(title?: string, canonical?: string): void {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = title;
    let link: HTMLLinkElement | null = null;
    let created = false;
    let before: string | null = null;
    if (canonical) {
      link = document.querySelector('link[rel="canonical"]');
      if (!link) {
        link = document.createElement('link');
        link.rel = 'canonical';
        document.head.appendChild(link);
        created = true;
      } else {
        before = link.getAttribute('href');
      }
      link.href = canonical;
    }
    return () => {
      document.title = previous;
      if (link) {
        if (created) link.remove();
        else if (before !== null) link.setAttribute('href', before);
      }
    };
  }, [title, canonical]);
}
