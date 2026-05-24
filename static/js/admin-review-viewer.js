/**
 * 리뷰 상세: Toast UI Viewer 또는 iframe 포함 시 HTML 직접 삽입.
 * 전제: #review-viewer-root, #review-body-json (type=application/json, 본문 JSON 문자열)
 */
(function () {
    'use strict';

    function readBodyHtml() {
        const el = document.getElementById('review-body-json');
        if (!el || !el.textContent) {
            return '';
        }
        try {
            return JSON.parse(el.textContent);
        } catch {
            return '';
        }
    }

    function render(html) {
        const root = document.getElementById('review-viewer-root');
        if (!root) {
            return;
        }
        const content = html || '';
        root.innerHTML = '';

        if (content.includes('<iframe')) {
            root.innerHTML = content;
            root.classList.add('toastui-editor-contents');
            return;
        }

        let attempts = 0;
        function tryViewer() {
            attempts += 1;
            if (!(window.toastui && window.toastui.Editor)) {
                if (attempts < 100) {
                    setTimeout(tryViewer, 80);
                } else {
                    root.innerHTML = content;
                    root.classList.add('toastui-editor-contents');
                }
                return;
            }
            try {
                window.toastui.Editor.factory({
                    el: root,
                    viewer: true,
                    initialValue: content,
                    usageStatistics: false,
                    language: 'ko',
                });
            } catch (e) {
                console.error(e);
                root.innerHTML = content;
                root.classList.add('toastui-editor-contents');
            }
        }

        tryViewer();
    }

    function boot() {
        render(readBodyHtml());
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
