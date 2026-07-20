/**
 * 블로그 작성·수정: Toast UI Editor(WYSIWYG) + 폼 hidden(content) 동기화 + 유튜브 임베드 삽입.
 * 전제 엘리먼트: #blog-admin-form, #blog-editor-el, #blog-content-hidden,
 *   #blog-initial-html-json(선택), #blog-youtube-url, #blog-yt-insert(선택), #blog-image-url
 */
(function () {
    'use strict';

    function waitForToastUi(cb) {
        if (window.toastui && window.toastui.Editor) { cb(); return; }
        var t0 = Date.now();
        var iv = setInterval(function () {
            if (window.toastui && window.toastui.Editor) { clearInterval(iv); cb(); }
            else if (Date.now() - t0 > 8000) { clearInterval(iv); console.error('Toast UI Editor 로드 시간 초과'); }
        }, 50);
    }

    function extractYoutubeId(url) {
        var m = String(url || '').match(/(?:shorts\/|watch\?v=|youtu\.be\/|\/v\/|embed\/)([0-9A-Za-z_-]{11})/);
        return m ? m[1] : '';
    }

    function embedBlockHtml(videoId) {
        var src = 'https://www.youtube.com/embed/' + videoId;
        return (
            '<div class="blog-yt-embed" style="position:relative;width:100%;aspect-ratio:16/9;margin:1.2rem 0;border-radius:14px;overflow:hidden;">' +
            '<iframe src="' + src + '" title="관련 영상" loading="lazy" ' +
            'style="position:absolute;inset:0;width:100%;height:100%;border:0;" ' +
            'allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" allowfullscreen></iframe></div>'
        );
    }

    function init() {
        var form = document.getElementById('blog-admin-form');
        var mount = document.getElementById('blog-editor-el');
        var hidden = document.getElementById('blog-content-hidden');
        if (!form || !mount || !hidden || window._blogTuiEditor) { return; }

        waitForToastUi(function () {
            var Editor = window.toastui.Editor;
            var initial = '';
            var jsonEl = document.getElementById('blog-initial-html-json');
            if (jsonEl && jsonEl.textContent) {
                try { initial = JSON.parse(jsonEl.textContent); } catch (e) { initial = ''; }
            }
            if (typeof initial !== 'string') { initial = ''; }

            window._blogTuiEditor = new Editor({
                el: mount,
                height: '520px',
                initialEditType: 'wysiwyg',
                previewStyle: 'tab',
                usageStatistics: false,
                language: 'ko',
                initialValue: initial,
                placeholder: '블로그 본문을 작성하세요. (정보성 + 상품 리뷰 혼합)',
                toolbarItems: [
                    ['heading', 'bold', 'italic', 'strike'],
                    ['hr', 'quote'],
                    ['ul', 'ol', 'task', 'indent', 'outdent'],
                    ['table', 'image', 'link'],
                    ['code', 'codeblock'],
                ],
            });

            // 유튜브 임베드: 본문 끝에 iframe 블록 append (+ youtube_url 필드도 세팅 → 공개 페이지 자동 임베드 보장).
            var ytBtn = document.getElementById('blog-yt-insert');
            if (ytBtn) {
                ytBtn.addEventListener('click', function () {
                    var urlEl = document.getElementById('blog-youtube-url');
                    var url = urlEl ? (urlEl.value || '').trim() : '';
                    var vid = extractYoutubeId(url);
                    if (!vid) { window.alert('유효한 유튜브 URL을 먼저 입력하세요 (shorts/watch/youtu.be).'); return; }
                    var ed = window._blogTuiEditor;
                    var html = (ed.getHTML() || '').trimEnd();
                    var block = embedBlockHtml(vid);
                    ed.setHTML(html ? html + '\n' + block : block);
                });
            }

            form.addEventListener('submit', function (e) {
                // 상품 이미지 필수 가드
                var img = document.getElementById('blog-image-url');
                if (img && !(img.value || '').trim()) {
                    e.preventDefault();
                    window.alert('상품 이미지 URL은 필수입니다 (텍스트만 글은 허용되지 않습니다).');
                    img.focus();
                    return;
                }
                hidden.value = window._blogTuiEditor.getHTML();
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
