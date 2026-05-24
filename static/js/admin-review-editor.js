/**
 * 리뷰 작성·수정: Toast UI Editor(WYSIWYG) + 폼 hidden(content) 동기화.
 * 전제: #review-admin-form, #review-editor-el, #review-content-hidden, #review-initial-html-json(선택)
 */
(function () {
    'use strict';

    function waitForToastUi(cb) {
        if (window.toastui && window.toastui.Editor) {
            cb();
            return;
        }
        const t0 = Date.now();
        const iv = setInterval(function () {
            if (window.toastui && window.toastui.Editor) {
                clearInterval(iv);
                cb();
            } else if (Date.now() - t0 > 8000) {
                clearInterval(iv);
                console.error('Toast UI Editor 로드 시간 초과');
            }
        }, 50);
    }

    function init() {
        const form = document.getElementById('review-admin-form');
        const mount = document.getElementById('review-editor-el');
        const hidden = document.getElementById('review-content-hidden');
        if (!form || !mount || !hidden) {
            return;
        }
        if (window._reviewTuiEditor) {
            return;
        }

        waitForToastUi(function () {
            const Editor = window.toastui.Editor;
            let initial = '';
            const jsonEl = document.getElementById('review-initial-html-json');
            if (jsonEl && jsonEl.textContent) {
                try {
                    initial = JSON.parse(jsonEl.textContent);
                } catch (e) {
                    initial = '';
                }
            }
            if (typeof initial !== 'string') {
                initial = '';
            }

            window._reviewTuiEditor = new Editor({
                el: mount,
                height: '500px',
                initialEditType: 'wysiwyg',
                previewStyle: 'tab',
                usageStatistics: false,
                language: 'ko',
                initialValue: initial,
                placeholder: '리뷰 본문을 작성하세요.',
                toolbarItems: [
                    ['heading', 'bold', 'italic', 'strike'],
                    ['hr', 'quote'],
                    ['ul', 'ol', 'task', 'indent', 'outdent'],
                    ['table', 'image', 'link'],
                    ['code', 'codeblock'],
                ],
            });

            function escapeHtmlAttr(s) {
                return String(s)
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');
            }

            function stripShortsReviewCta(html) {
                return String(html || '').replace(
                    /<p\s+class=["']shorts-review-cta["'][^>]*>[\s\S]*?<\/p>\s*/gi,
                    ''
                );
            }

            function buildShortsCtaHtml(deeplink) {
                const href = escapeHtmlAttr(deeplink);
                return (
                    '<p class="shorts-review-cta">' +
                    '<a href="' +
                    href +
                    '" target="_blank" rel="noopener noreferrer" ' +
                    'class="btn btn-primary" style="display:inline-block;text-decoration:none;">' +
                    '쿠팡에서 구매하기</a></p>'
                );
            }

            const ctaBtn = document.getElementById('review-cta-insert');
            if (ctaBtn) {
                ctaBtn.addEventListener('click', function () {
                    const ps = document.getElementById('review-product');
                    if (!ps || !window._reviewTuiEditor) {
                        return;
                    }
                    const opt = ps.options[ps.selectedIndex];
                    if (!opt || !opt.value) {
                        window.alert('연결 상품에서 항목을 먼저 선택하세요.');
                        return;
                    }
                    const dl = (opt.getAttribute('data-deeplink') || '').trim();
                    if (!dl) {
                        window.alert('선택한 상품에 딥링크가 없습니다. 시트 G열 또는 DB 쿠팡 URL을 확인하세요.');
                        return;
                    }
                    const ed = window._reviewTuiEditor;
                    let html = stripShortsReviewCta(ed.getHTML()).trimEnd();
                    const block = buildShortsCtaHtml(dl);
                    if (html) {
                        ed.setHTML(html + '\n' + block);
                    } else {
                        ed.setHTML(block);
                    }
                });
            }

            form.addEventListener('submit', function () {
                hidden.value = window._reviewTuiEditor.getHTML();
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
