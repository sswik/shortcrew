/**
 * 리뷰 폼: AI 글쓰기 모달 → 상품·인플루언서 기반 초안 생성 → Toast 에디터·제목 반영.
 */
(function () {
    'use strict';

    var API_URL = '/admin/api/ops/ai/review-draft';
    var lastDraft = null;

    function $(id) {
        return document.getElementById(id);
    }

    function openModal() {
        var modal = $('review-ai-modal');
        if (!modal) return;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        modal.setAttribute('aria-hidden', 'false');
        $('review-ai-error').classList.add('hidden');
        $('review-ai-error').textContent = '';
        $('review-ai-result').classList.add('hidden');
        $('review-ai-apply').disabled = true;
        lastDraft = null;
    }

    function closeModal() {
        var modal = $('review-ai-modal');
        if (!modal) return;
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        modal.setAttribute('aria-hidden', 'true');
    }

    function waitForEditor(cb, maxMs) {
        var t0 = Date.now();
        maxMs = maxMs || 10000;
        var iv = setInterval(function () {
            if (window._reviewTuiEditor && typeof window._reviewTuiEditor.setHTML === 'function') {
                clearInterval(iv);
                cb(window._reviewTuiEditor);
            } else if (Date.now() - t0 > maxMs) {
                clearInterval(iv);
                cb(null);
            }
        }, 80);
    }

    function applyDraft() {
        if (!lastDraft) return;
        waitForEditor(function (editor) {
            if (!editor) {
                alert('에디터가 아직 준비되지 않았습니다. 잠시 후 다시 눌러 주세요.');
                return;
            }
            var titleInput = $('review-title');
            if (titleInput && lastDraft.title) {
                titleInput.value = lastDraft.title;
            }
            editor.setHTML(lastDraft.html || '<p></p>');
            closeModal();
        });
    }

    async function generateDraft() {
        var productSel = $('review-product');
        var infSel = $('review-influencer');
        var errEl = $('review-ai-error');
        var genBtn = $('review-ai-generate');
        if (!productSel || !infSel) return;

        var productId = (productSel.value || '').trim();
        if (!productId) {
            errEl.textContent = '먼저 폼에서 연결 상품을 선택하세요.';
            errEl.classList.remove('hidden');
            return;
        }
        var pidNum = parseInt(productId, 10);
        if (!Number.isFinite(pidNum) || pidNum < 1) {
            errEl.textContent =
                'DB에 연동된 상품만 AI 글쓰기를 쓸 수 있습니다. (시트만 연결 옵션은 불가)';
            errEl.classList.remove('hidden');
            return;
        }

        errEl.classList.add('hidden');
        errEl.textContent = '';
        genBtn.disabled = true;
        genBtn.textContent = '생성 중…';

        try {
            var res = await fetch(API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    product_id: pidNum,
                    influencer_slug: infSel.value || '',
                    extra_instruction: ($('review-ai-extra') && $('review-ai-extra').value) || '',
                }),
            });
            var data = await res.json().catch(function () {
                return {};
            });
            if (!res.ok) {
                errEl.textContent = data.error || '생성에 실패했습니다.';
                errEl.classList.remove('hidden');
                return;
            }
            lastDraft = { title: data.title || '', html: data.html || '' };
            $('review-ai-result-title').textContent = lastDraft.title;
            $('review-ai-result-preview').innerHTML = lastDraft.html;
            $('review-ai-result').classList.remove('hidden');
            $('review-ai-apply').disabled = false;
        } catch (e) {
            errEl.textContent = String(e.message || e);
            errEl.classList.remove('hidden');
        } finally {
            genBtn.disabled = false;
            genBtn.textContent = '생성';
        }
    }

    function init() {
        var openBtn = $('btn-review-ai-open');
        var modal = $('review-ai-modal');
        if (!openBtn || !modal) return;

        openBtn.addEventListener('click', openModal);
        $('review-ai-close').addEventListener('click', closeModal);
        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeModal();
        });
        $('review-ai-generate').addEventListener('click', generateDraft);
        $('review-ai-apply').addEventListener('click', applyDraft);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
