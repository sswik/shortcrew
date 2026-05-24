/**
 * 상품 관리(/admin/products) — sample/ops dashboard 동작.
 * API: /admin/api/ops (경로 오버라이드 시 window.__ADMIN_PRODUCTS_API_BASE__)
 */
(function () {
    'use strict';

        const channelSelect = document.getElementById('channelSelect');
        const trendSection = document.getElementById('trendSection');
        const trendDiscovery = document.getElementById('trendDiscovery');
        const trendMonitoring = document.getElementById('trendMonitoring');
        const searchKeyword = document.getElementById('searchKeyword');
        const searchBtn = document.getElementById('searchBtn');
        const searchResults = document.getElementById('searchResults');
        const searchMeta = document.getElementById('searchMeta');
        const confirmTable = document.getElementById('confirmTable');
        const sendSheetBtn = document.getElementById('sendSheetBtn');
        const itemCount = document.getElementById('itemCount');
        
        // 모달 관련
        const statusModal = document.getElementById('statusModal');
        const statusIcon = document.getElementById('statusIcon');
        const statusTitle = document.getElementById('statusTitle');
        const statusMessage = document.getElementById('statusMessage');

        let confirmedList = [];
        let previewTimer = null;

        function escapeHtml(s) {
            const d = document.createElement('div');
            d.textContent = s == null ? '' : s;
            return d.innerHTML;
        }

        /** API/네트워크 예외에서 사용자에게 보일 문장 (서버 `error`/`detail`은 apiGet/apiPostJson 이 message 로 넘김). */
        function formatApiError(e, fallback) {
            if (e && typeof e.message === 'string' && e.message.trim()) {
                return e.message.trim();
            }
            return (fallback && String(fallback).trim()) || '요청에 실패했습니다.';
        }

        // ✅ 개선된 상태 알림 함수 (모달 팝업)
        function showStatus(title, msg, type = 'success') {
            statusTitle.textContent = title;
            statusMessage.textContent = msg;
            
            if (type === 'success') {
                statusIcon.innerHTML = '✅';
                statusIcon.className = 'w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl bg-green-100 text-green-600';
            } else if (type === 'error') {
                statusIcon.innerHTML = '❌';
                statusIcon.className = 'w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl bg-red-100 text-red-600';
            } else {
                statusIcon.innerHTML = '⚠️';
                statusIcon.className = 'w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl bg-amber-100 text-amber-600';
            }
            
            statusModal.classList.remove('hidden');
            document.body.classList.add('overflow-hidden'); // 배경 스크롤 잠금
        }

        function closeStatusModal() {
            statusModal.classList.add('hidden');
            document.body.classList.remove('overflow-hidden'); // 배경 스크롤 해제
        }

        const API_BASE = typeof window.__ADMIN_PRODUCTS_API_BASE__ !== 'undefined'
            ? window.__ADMIN_PRODUCTS_API_BASE__
            : '/admin/api/ops';

        async function apiGet(path) {
            const r = await fetch(API_BASE + path, { credentials: 'same-origin', redirect: 'manual' });
            if (r.status === 302 || r.status === 303) {
                const loc = r.headers.get('Location') || '';
                if (loc.includes('/admin/login')) {
                    window.location.href = loc.startsWith('http') ? loc : new URL(loc, window.location.origin).href;
                    throw new Error('로그인이 필요합니다.');
                }
            }
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                throw new Error(err.detail || err.error || '요청 실패 ' + r.status);
            }
            const ct = r.headers.get('content-type') || '';
            if (ct.includes('text/html')) {
                window.location.href = '/admin/login';
                throw new Error('로그인이 필요합니다.');
            }
            return r.json();
        }

        async function apiPostJson(path, body) {
            const r = await fetch(API_BASE + path, {
                method: 'POST',
                credentials: 'same-origin',
                redirect: 'manual',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (r.status === 302 || r.status === 303) {
                const loc = r.headers.get('Location') || '';
                if (loc.includes('/admin/login')) {
                    window.location.href = loc.startsWith('http') ? loc : new URL(loc, window.location.origin).href;
                    throw new Error('로그인이 필요합니다.');
                }
            }
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                throw new Error(data.detail || data.error || '요청 실패 ' + r.status);
            }
            return data;
        }

        async function loadChannels() {
            channelSelect.innerHTML = '<option value="">-- 자동화 채널을 선택하세요 --</option>';
            try {
                const data = await apiGet('/channels');
                (data.channels || []).forEach(ch => {
                    const opt = document.createElement('option');
                    opt.value = ch.channel_id;
                    opt.textContent = ch.name;
                    channelSelect.appendChild(opt);
                });
            } catch (e) {
                console.error('채널 로드 실패:', e);
                alert('채널 목록을 불러올 수 없습니다. 로그인 상태를 확인한 뒤 다시 시도해 주세요.');
            }
        }

        function renderKeywordBadges(container, list, badgeClass, emptyMsg) {
            container.innerHTML = '';
            if (!list || list.length === 0) {
                container.innerHTML = '<span class="text-slate-400 text-sm italic">' + (emptyMsg || '없음') + '</span>';
                return;
            }
            list.forEach(k => {
                const span = document.createElement('span');
                span.dataset.keyword = k.keyword || '';
                span.className = 'cursor-pointer px-3 py-1.5 rounded-full text-xs font-semibold transition-all shadow-sm active:scale-90 ' + badgeClass;
                span.innerHTML = '# ' + escapeHtml(k.keyword) + ' <span class="opacity-80 ml-1 text-[10px] font-normal">' + (k.rank || '') + '위</span>';
                span.addEventListener('click', () => {
                    searchKeyword.value = span.dataset.keyword;
                    doSearch();
                });
                container.appendChild(span);
            });
        }

        async function loadTrendForChannel(cid) {
            trendSection.classList.toggle('hidden', !cid);
            trendDiscovery.innerHTML = '';
            trendMonitoring.innerHTML = '';
            if (!cid) return;
            try {
                const data = await apiGet('/naver/trend?channel_id=' + encodeURIComponent(cid));
                const discovery = data.discovery || [];
                const seedKeywords = data.seed_keywords || discovery;
                window.currentDiscoveryKeywords = discovery;
                window.currentSeedKeywords = seedKeywords;
                const monitoring = data.monitoring || [];
                renderKeywordBadges(trendDiscovery, discovery, 'bg-indigo-100 border border-indigo-200 text-indigo-700 hover:bg-indigo-500 hover:text-white hover:border-indigo-500');
                renderKeywordBadges(trendMonitoring, monitoring, 'bg-emerald-100 border border-emerald-200 text-emerald-700 hover:bg-emerald-500 hover:text-white hover:border-emerald-500', '관심 키워드가 설정되지 않았습니다.');
            } catch (e) {
                console.error(e);
            }
        }

        const registeredTable = document.getElementById('registeredTable');
        const registeredEmpty = document.getElementById('registeredEmpty');
        const registeredPagination = document.getElementById('registeredPagination');
        const registeredSortSelect = document.getElementById('registeredSortSelect');
        const btnStatusPublish = document.getElementById('btnStatusPublish');
        const btnStatusWait = document.getElementById('btnStatusWait');

        let registeredItemsList = [];
        let registeredCurrentPage = 1;
        const REGISTERED_PAGE_SIZE = 20;

        function formatRegDate(val) {
            if (!val) return '';
            const s = String(val).trim();
            if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
            const d = new Date(s);
            if (isNaN(d.getTime())) return s;
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return y + '-' + m + '-' + day;
        }

        // 딥링크 원클릭 복사
        function copyDeepLink(link) {
            navigator.clipboard.writeText(link).then(() => {
                showStatus('복사 완료', '딥링크가 클립보드에 복사되었습니다. 외부 게시에 바로 사용할 수 있습니다.', 'success');
            }).catch((err) => {
                console.error('복사 에러:', err);
                alert('클립보드 복사에 실패했습니다.');
            });
        }

        // 누락된 링크 클릭 시 치명 경고
        function alertMissingLink() {
            showStatus('수익 누락 경고', '이 상품은 딥링크가 생성되지 않았습니다. 일반 URL을 사용하면 파트너스 수익이 집계되지 않을 수 있습니다.', 'error');
        }

        function renderRegisteredTable() {
            registeredTable.innerHTML = '';
            if (registeredPagination) registeredPagination.classList.add('hidden');
            if (!registeredItemsList.length) {
                if (registeredEmpty) { registeredEmpty.classList.remove('hidden'); registeredEmpty.textContent = '등록된 상품이 없습니다.'; }
                return;
            }
            const sortOrder = (registeredSortSelect && registeredSortSelect.value) || 'newest';
            const sorted = sortOrder === 'oldest' ? registeredItemsList.slice() : registeredItemsList.slice().reverse();
            const totalPages = Math.max(1, Math.ceil(sorted.length / REGISTERED_PAGE_SIZE));
            registeredCurrentPage = Math.min(Math.max(1, registeredCurrentPage), totalPages);
            const start = (registeredCurrentPage - 1) * REGISTERED_PAGE_SIZE;
            const pageItems = sorted.slice(start, start + REGISTERED_PAGE_SIZE);

            pageItems.forEach(it => {
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-50';
                const status = (it.status || '').trim() || '대기';
                const statusClass = status === '게시중' ? 'bg-emerald-100 text-emerald-800 px-2 py-1 rounded text-xs font-medium' : 'bg-amber-100 text-amber-800 px-2 py-1 rounded text-xs font-medium';
                const deepLink = (it.deepLink || '').trim();
                const regDate = formatRegDate(it.regDate);
                const linkActionHtml = deepLink
                    ? '<div class="flex flex-col items-center gap-1">' +
                      '<a href="' + escapeHtml(deepLink) + '" target="_blank" rel="noopener" class="text-indigo-600 hover:text-indigo-800 font-bold hover:underline text-[10px]">테스트</a>' +
                      '<button type="button" data-copy-link="' + escapeHtml(deepLink) + '" class="w-full bg-indigo-50 hover:bg-indigo-600 hover:text-white text-indigo-700 border border-indigo-200 text-xs font-bold py-1 px-2 rounded transition-colors shadow-sm">복사</button>' +
                      '</div>'
                    : '<button type="button" data-missing-link="1" class="w-full bg-red-500 hover:bg-red-600 text-white text-xs font-bold py-1.5 px-2 rounded shadow-sm animate-pulse">누락됨!</button>';
                tr.innerHTML =
                    '<td class="px-3 py-2 w-10 text-center"><input type="checkbox" class="registered-row-cb" data-row-index="' + escapeHtml(String(it.row_index)) + '"></td>' +
                    '<td class="px-3 py-2 w-16 text-center"><img src="' + escapeHtml(it.imageUrl || '') + '" alt="" class="w-12 h-12 object-cover rounded border border-slate-200 mx-auto" onerror="this.style.display=\'none\'"></td>' +
                    '<td class="px-3 py-2 max-w-[180px] md:max-w-[240px]"><div class="truncate font-medium text-slate-700" title="' + escapeHtml(it.productName || '') + '">' + escapeHtml(it.productName || '') + '</div></td>' +
                    '<td class="px-3 py-2 w-[7.5rem] text-slate-600 whitespace-nowrap">' + escapeHtml(regDate) + '</td>' +
                    '<td class="px-3 py-2 w-28 font-medium text-slate-600 whitespace-nowrap text-right">' + Number(it.price || 0).toLocaleString() + '원</td>' +
                    '<td class="px-3 py-2 w-20 text-center ' + (deepLink ? '' : 'bg-red-50 border-l border-r border-red-200') + '">' + linkActionHtml + '</td>' +
                    '<td class="px-3 py-2 w-24 text-center"><span class="' + statusClass + ' whitespace-nowrap">' + escapeHtml(status) + '</span></td>';
                registeredTable.appendChild(tr);
            });

            registeredTable.querySelectorAll('[data-copy-link]').forEach((btn) => {
                btn.addEventListener('click', () => copyDeepLink(btn.getAttribute('data-copy-link') || ''));
            });
            registeredTable.querySelectorAll('[data-missing-link]').forEach((btn) => {
                btn.addEventListener('click', () => alertMissingLink());
            });

            const selectAll = document.getElementById('registeredSelectAll');
            if (selectAll) {
                selectAll.checked = false;
                selectAll.onclick = function () {
                    registeredTable.querySelectorAll('.registered-row-cb').forEach(cb => { cb.checked = selectAll.checked; });
                };
            }

            if (registeredPagination && sorted.length > 0) {
                registeredPagination.classList.remove('hidden');
                const end = Math.min(start + REGISTERED_PAGE_SIZE, sorted.length);
                const rangeText = '총 ' + sorted.length + '개 중 ' + (start + 1) + '~' + end + '개 표시';
                let rightHtml = '';
                if (totalPages > 1) {
                    rightHtml = '<div class="flex items-center gap-1 flex-wrap">';
                    for (let i = 1; i <= totalPages; i++) {
                        const isCurrent = i === registeredCurrentPage;
                        rightHtml += '<button type="button" class="registered-page-num px-2.5 py-1.5 rounded border text-sm font-medium ' + (isCurrent ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 text-slate-700 hover:bg-slate-50') + '" data-page="' + i + '">' + i + '</button>';
                    }
                    rightHtml += '</div>';
                }
                registeredPagination.innerHTML = '<span class="text-sm text-slate-600">' + rangeText + '</span>' + rightHtml;
                registeredPagination.querySelectorAll('.registered-page-num').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        const p = parseInt(btn.dataset.page, 10);
                        if (!isNaN(p) && p >= 1 && p <= totalPages) {
                            registeredCurrentPage = p;
                            renderRegisteredTable();
                        }
                    });
                });
            }
        }

        /** @returns {Promise<boolean>} 시트 목록을 정상적으로 받았으면 true */
        async function loadRegisteredItems() {
            const cid = channelSelect.value;
            registeredTable.innerHTML = '';
            if (registeredEmpty) registeredEmpty.classList.add('hidden');
            if (registeredPagination) registeredPagination.classList.add('hidden');
            if (!cid) {
                if (registeredEmpty) { registeredEmpty.classList.remove('hidden'); registeredEmpty.textContent = '채널을 선택하세요.'; }
                return false;
            }
            try {
                const data = await apiGet('/sheets/items?channel_id=' + encodeURIComponent(cid));
                registeredItemsList = data.items || [];
                registeredCurrentPage = 1;
                if (registeredItemsList.length === 0) {
                    if (registeredEmpty) { registeredEmpty.classList.remove('hidden'); registeredEmpty.textContent = '등록된 상품이 없습니다.'; }
                    return true;
                }
                renderRegisteredTable();
                return true;
            } catch (e) {
                console.error('등록 상품 로드 실패:', e);
                const msg = formatApiError(e, '등록 상품 목록을 불러오지 못했습니다.');
                if (registeredEmpty) {
                    registeredEmpty.classList.remove('hidden');
                    registeredEmpty.textContent = msg;
                }
                showStatus('등록 상품 로드 실패', msg, 'error');
                return false;
            }
        }

        if (registeredSortSelect) {
            registeredSortSelect.addEventListener('change', function () {
                registeredCurrentPage = 1;
                renderRegisteredTable();
            });
        }

        async function changeStatus(newStatus) {
            const cid = channelSelect.value;
            if (!cid) {
                showStatus('알림', '채널을 먼저 선택하세요.', 'warning');
                return;
            }
            const checkboxes = registeredTable.querySelectorAll('.registered-row-cb:checked');
            if (!checkboxes.length) {
                showStatus('알림', '변경할 항목을 선택하세요.', 'warning');
                return;
            }

            // 게시중 변경 시 딥링크 누락 항목이 포함되면 API 호출 전 차단
            if (newStatus === '게시중') {
                let hasMissingLink = false;
                checkboxes.forEach((cb) => {
                    const rowIndex = parseInt(cb.dataset.rowIndex, 10);
                    const item = registeredItemsList.find((it) => Number(it.row_index) === rowIndex);
                    if (item && (!item.deepLink || String(item.deepLink).trim() === '')) {
                        hasMissingLink = true;
                    }
                });
                if (hasMissingLink) {
                    showStatus('게시 차단됨', '선택 항목 중 딥링크가 없는 상품이 있습니다. 수익 누락 방지를 위해 게시중 변경을 중단했습니다.', 'error');
                    return;
                }
            }
            const updates = [];
            checkboxes.forEach(cb => {
                const rowIndex = parseInt(cb.dataset.rowIndex, 10);
                if (!isNaN(rowIndex)) updates.push({ row_index: rowIndex, new_status: newStatus });
            });
            if (!updates.length) return;
            const btn = newStatus === '게시중' ? btnStatusPublish : btnStatusWait;
            const origText = btn ? btn.textContent : '';
            if (btn) { btn.disabled = true; btn.textContent = '처리 중...'; }
            try {
                const data = await apiPostJson('/sheets/items/status', { channel_id: cid, updates });
                showStatus('완료', data.message || '상태 변경 완료', 'success');
                await loadRegisteredItems();
            } catch (e) {
                showStatus('상태 변경 실패', formatApiError(e, '요청에 실패했습니다.'), 'error');
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = origText; }
            }
        }

        channelSelect.addEventListener('change', () => {
            loadTrendForChannel(channelSelect.value);
            loadRegisteredItems();
            scheduleDeeplinkPreview();
        });

        function scheduleDeeplinkPreview() {
            clearTimeout(previewTimer);
            previewTimer = setTimeout(function () {
                refreshDeeplinkPreview().catch(function () { /* 미리보기 실패는 전송 시 재시도 */ });
            }, 450);
        }

        async function refreshDeeplinkPreview() {
            const cid = channelSelect.value;
            if (!cid || !confirmedList.length) return;
            const r = await fetch(API_BASE + '/sheets/deeplink-preview', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_id: cid, products: confirmedList }),
            });
            const data = await r.json().catch(() => ({}));
            if (r.status === 409 && data.status === 'deeplink_required') {
                showStatus(
                    '딥링크 미리보기',
                    (data.error || '딥링크 생성에 실패했습니다.') +
                        ' 실패 ' +
                        String(data.failed_count || 0) +
                        '건 — 쿠팡 키·상품 ID를 확인하세요.',
                    'warning'
                );
                return;
            }
            if (!r.ok) {
                return;
            }
            const byId = {};
            (data.products || []).forEach(function (p) {
                if (p && p.productId != null) byId[p.productId] = p;
            });
            confirmedList = confirmedList.map(function (p) {
                var m = byId[p.productId];
                if (!m) return p;
                return Object.assign({}, p, {
                    deepLink: m.deepLink != null ? m.deepLink : p.deepLink,
                });
            });
            renderConfirmTable();
        }

        const btnRefreshRegistered = document.getElementById('btnRefreshRegistered');
        if (btnRefreshRegistered) {
            btnRefreshRegistered.addEventListener('click', async function () {
                const cid = channelSelect.value;
                if (!cid) {
                    showStatus('알림', '채널을 먼저 선택하세요.', 'warning');
                    return;
                }
                const orig = btnRefreshRegistered.textContent;
                btnRefreshRegistered.disabled = true;
                btnRefreshRegistered.textContent = '불러오는 중…';
                try {
                    const ok = await loadRegisteredItems();
                    if (ok) {
                        showStatus('목록 갱신', '시트에서 등록 상품 목록만 다시 불러왔습니다.', 'success');
                    }
                } finally {
                    btnRefreshRegistered.disabled = false;
                    btnRefreshRegistered.textContent = orig;
                }
            });
        }

        const btnMallImport = document.getElementById('btnMallImport');
        if (btnMallImport) {
            btnMallImport.addEventListener('click', async function () {
                const cid = channelSelect.value;
                if (!cid) {
                    showStatus('알림', '채널을 먼저 선택하세요.', 'warning');
                    return;
                }
                btnMallImport.disabled = true;
                try {
                    const data = await apiPostJson('/sheets/mall-import', { channel_id: cid });
                    const w = data.warning ? ' ' + String(data.warning) : '';
                    const r = Number(data.sheet_rows || 0);
                    const apiOk = !!data.mall_products_api_configured;
                    showStatus(
                        '몰 시트 연동',
                        '공개 몰(/shop)은 시트 웹앱 JSON만 사용합니다. 시트 데이터 행(헤더 제외) ' + r + '건.' +
                            (apiOk ? ' 몰 GET URL 설정됨(또는 전달 웹훅 URL 폴백).' : ' PRODUCT_DELIVERY / MALL_PRODUCTS URL 모두 비어 있음.') + w,
                        apiOk ? 'success' : 'warning'
                    );
                } catch (e) {
                    showStatus('몰 DB 반영 실패', formatApiError(e, '요청에 실패했습니다.'), 'error');
                } finally {
                    btnMallImport.disabled = false;
                }
            });
        }

        const channelSettingsModal = document.getElementById('channelSettingsModal');
        const monitorKeywordsInput = document.getElementById('monitorKeywordsInput');
        const channelSettingsBtn = document.getElementById('channelSettingsBtn');
        const channelSettingsCancel = document.getElementById('channelSettingsCancel');
        const channelSettingsSave = document.getElementById('channelSettingsSave');

        channelSettingsBtn.addEventListener('click', async () => {
            const cid = channelSelect.value;
            if (!cid) {
                showStatus('알림', '채널을 먼저 선택하세요.', 'warning');
                return;
            }
            channelSettingsModal.classList.remove('hidden');
            document.body.classList.add('overflow-hidden'); // 배경 스크롤 잠금
            try {
                const data = await apiGet('/channels/' + encodeURIComponent(cid) + '/settings');
                monitorKeywordsInput.value = (data.monitor_keywords || []).join(', ');
            } catch (e) { monitorKeywordsInput.value = ''; }
        });

        function closeSettingsModal() {
            channelSettingsModal.classList.add('hidden');
            document.body.classList.remove('overflow-hidden'); // 배경 스크롤 해제
        }
        channelSettingsCancel.addEventListener('click', closeSettingsModal);
        
        channelSettingsSave.addEventListener('click', async () => {
            const cid = channelSelect.value;
            if (!cid) return;
            const monitor_keywords = monitorKeywordsInput.value.split(',').map(s => s.trim()).filter(Boolean);
            try {
                await apiPostJson('/channels/' + encodeURIComponent(cid) + '/settings', { monitor_keywords });
                closeSettingsModal();
                await loadTrendForChannel(cid);
            } catch (e) { alert('저장 실패'); }
        });

        async function doSearch() {
            const kw = searchKeyword.value.trim();
            if (!kw) return;
            searchMeta.textContent = '검색 중...';
            searchResults.innerHTML = '<div class="flex justify-center p-10"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div></div>';
            try {
                const data = await apiGet('/coupang/search?keyword=' + encodeURIComponent(kw) + '&limit=20');
                const products = data.products || [];
                const requestedLimit = Number(data.requested_limit || 20);
                const returnedCount = Number(data.returned_count || products.length);
                const rawCollected = Number(data.raw_collected != null ? data.raw_collected : returnedCount);
                const filteredCount = Number(data.filtered_count != null ? data.filtered_count : returnedCount);
                const stopReason = data.stop_reason || '';
                const stopLabels = {
                    target_met: '요청 개수까지 확보',
                    no_new_items_on_page: '다음 페이지에 신규 상품 없음',
                    empty_page: '빈 페이지로 종료',
                    exhausted_queries: '요청·페이지 순회 완료',
                };
                const stopNote = stopLabels[stopReason] || stopReason;
                searchMeta.textContent =
                    '요청 ' + requestedLimit + '개 · API 수집(중복 제거) ' + rawCollected + '건 · 필터 통과 ' + filteredCount + '건 · 표시 ' + returnedCount + '건' +
                    (stopNote ? ' · ' + stopNote : '');
                searchResults.innerHTML = products.length ? '<div class="grid grid-cols-1 gap-3 p-1">' + products.map(p =>
                    '<div class="flex items-center gap-3 bg-white p-3 rounded-lg shadow-sm border border-slate-100 hover:border-indigo-300 transition-all">' +
                    '<img class="w-16 h-16 rounded object-cover border" src="' + escapeHtml(p.imageUrl || '') + '">' +
                    '<div class="flex-1 min-w-0">' +
                    '<div class="text-xs font-bold text-slate-700 truncate">' + escapeHtml(p.productName || '') + '</div>' +
                    '<div class="text-indigo-600 font-bold text-sm">₩' + Number(p.price || 0).toLocaleString() + '</div>' +
                    '</div><button type="button" data-add class="bg-slate-100 hover:bg-indigo-600 hover:text-white text-slate-600 font-bold py-2 px-3 rounded text-xs transition-colors">추가</button></div>'
                ).join('') + '</div>' : '<p class="text-center p-10 text-slate-400 text-sm">결과가 없습니다.</p>';
                searchResults.querySelectorAll('[data-add]').forEach((btn, i) => btn.addEventListener('click', () => addToConfirm(products[i])));
            } catch (e) {
                searchMeta.textContent = '요청 실패';
                searchResults.innerHTML = '에러';
            }
        }

        function addToConfirm(p) {
            if (confirmedList.some(x => x.productId === p.productId)) return;
            confirmedList.push({ ...p });
            renderConfirmTable();
            scheduleDeeplinkPreview();
        }

        function removeFromConfirm(productId) {
            confirmedList = confirmedList.filter(x => x.productId !== productId);
            renderConfirmTable();
            scheduleDeeplinkPreview();
        }

        function renderConfirmTable() {
            itemCount.textContent = confirmedList.length + '개 선택됨';
            confirmTable.innerHTML = confirmedList.map(p => {
                var dl = String(p.deepLink || '').trim();
                var linkHint = dl
                    ? '<div class="text-[10px] text-emerald-600 truncate max-w-[220px]" title="' + escapeHtml(dl) + '">딥링크 준비됨</div>'
                    : '<div class="text-[10px] text-slate-400">딥링크 미리보기 대기…</div>';
                return (
                    '<tr class="hover:bg-slate-50 transition-colors"><td class="px-4 py-3"><img class="w-10 h-10 rounded shadow-sm border object-cover" src="' + escapeHtml(p.imageUrl || '') + '"></td>' +
                    '<td class="px-4 py-3"><input class="w-full bg-transparent border-none focus:ring-1 focus:ring-indigo-300 text-xs font-medium text-slate-700 p-1 rounded" type="text" value="' + escapeHtml(p.productName || '') + '" data-field="productName">' +
                    '<div class="text-[10px] text-indigo-500 font-bold mt-1">₩' + Number(p.price || 0).toLocaleString() + '</div>' +
                    linkHint + '</td>' +
                    '<td class="px-4 py-3 text-center"><button type="button" data-remove class="text-slate-300 hover:text-red-500 p-2"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg></button></td></tr>'
                );
            }).join('');
            confirmTable.querySelectorAll('[data-remove]').forEach((btn, i) => btn.addEventListener('click', () => removeFromConfirm(confirmedList[i].productId)));
        }

        searchBtn.addEventListener('click', doSearch);
        searchKeyword.addEventListener('keypress', (e) => { if (e.key === 'Enter') doSearch(); });

        sendSheetBtn.addEventListener('click', async () => {
            const cid = channelSelect.value;
            if (!cid) { showStatus('알림', '채널을 먼저 선택하세요.', 'warning'); return; }
            if (!confirmedList.length) { showStatus('알림', '전송할 상품이 없습니다.', 'warning'); return; }

            const originalBtnHtml = sendSheetBtn.innerHTML;
            sendSheetBtn.innerHTML = '<span class="animate-spin inline-block mr-2">⏳</span> 중복 검사 및 전송 중...';
            sendSheetBtn.disabled = true;

            try {
                const data = await apiPostJson('/sheets/send', { channel_id: cid, products: confirmedList });
                if (data.status === 'duplicate') {
                    showStatus('중복 방어 완료', data.message || '전부 중복된 상품입니다.', 'warning');
                } else if ((data.failed_count || 0) > 0) {
                    const failedCount = Number(data.failed_count || 0);
                    showStatus('전송은 완료됐지만 주의 필요', (data.message || '전송 완료') + ' 딥링크 미생성 ' + failedCount + '건이 있어 외부 게시를 차단하세요.', 'warning');
                } else {
                    showStatus('전송 성공', data.message || '전송 완료', 'success');
                }
                confirmedList = [];
                renderConfirmTable();
            } catch (e) {
                showStatus('시트 전송 실패', formatApiError(e, '시트 전송에 실패했습니다.'), 'error');
            } finally {
                sendSheetBtn.innerHTML = originalBtnHtml;
                sendSheetBtn.disabled = false;
            }
        });

        // 💡 과금 방어를 위한 메모리 캐시 변수
        let cachedCurationData = null;
        let cachedRequestHash = "";

        // 모드('auto' 또는 'custom')를 인자로 받습니다.
        async function runAICuration(mode) {
            const btnAuto = document.getElementById('btn-ai-auto');
            const btnCustom = document.getElementById('btn-ai-custom');
            const channelId = channelSelect.value;
            const promptInput = document.getElementById('aiCustomPrompt');

            let customPrompt = "";

            // 💡 수동 모드일 때는 입력값을 읽고, 자동 모드일 때는 무시합니다.
            if (mode === 'custom') {
                customPrompt = promptInput.value.trim();
                if (!customPrompt) {
                    alert("맞춤 조건을 입력해주세요! (예: 5만원 이하, 여름 시즌)");
                    promptInput.focus();
                    return;
                }
            } else {
                customPrompt = ""; // 자동 모드면 지시사항 없음
                promptInput.value = ""; // 헷갈리지 않게 입력창 비워줌
            }

            let keywords = Array.from(document.querySelectorAll('#trendDiscovery span[data-keyword]')).map(el => el.dataset.keyword).filter(Boolean);
            let seedKeywords = Array.isArray(window.currentSeedKeywords) ? window.currentSeedKeywords : [];
            if ((!seedKeywords || seedKeywords.length === 0) && typeof window.currentDiscoveryKeywords !== 'undefined' && window.currentDiscoveryKeywords.length) {
                seedKeywords = window.currentDiscoveryKeywords;
            }
            if (keywords.length === 0 && seedKeywords.length) {
                keywords = seedKeywords.map(k => (k && k.keyword) ? k.keyword : '').filter(Boolean);
            }

            if (!keywords || keywords.length === 0) {
                alert('분석할 네이버 트렌드 키워드가 없습니다.');
                return;
            }

            // 💰 비용 방어 로직
            const currentRequestHash = `${channelId}|${keywords.join(',')}|${customPrompt}`;
            if (cachedCurationData && cachedRequestHash === currentRequestHash) {
                console.log("캐시된 데이터 재사용 (과금 방어)");
                renderAIModal(cachedCurationData);
                return;
            }

            // 버튼 상태 변경 (둘 다 잠금)
            const originalAutoText = btnAuto.innerHTML;
            const originalCustomText = btnCustom.innerHTML;
            btnAuto.disabled = true;
            btnCustom.disabled = true;

            if (mode === 'auto') btnAuto.innerHTML = '⏳ AI 분석 중...';
            else btnCustom.innerHTML = '⏳ 조건 맞춰 분석 중...';

            try {
                const data = await apiPostJson('/ai/curate', {
                        channel_id: channelId,
                        seed_keywords: seedKeywords,
                        keywords: keywords,
                        custom_prompt: customPrompt
                    });

                cachedCurationData = data.items || [];
                cachedRequestHash = currentRequestHash;

                document.getElementById('btn-ai-reopen').classList.remove('hidden');
                renderAIModal(cachedCurationData);
            } catch (error) {
                console.error('AI 에러:', error);
                alert('에러 발생: ' + error.message);
            } finally {
                // 버튼 원상복구
                btnAuto.disabled = false;
                btnCustom.disabled = false;
                btnAuto.innerHTML = originalAutoText;
                btnCustom.innerHTML = originalCustomText;
            }
        }

        // 💡 모달 다시 열기 함수
        function openLastAIModal() {
            if (cachedCurationData) renderAIModal(cachedCurationData);
        }

        function renderAIModal(items) {
            const contentDiv = document.getElementById('ai-curation-content');
            contentDiv.innerHTML = '';
            if (!items || items.length === 0) {
                contentDiv.innerHTML = '<p class="text-sm text-slate-500">추천할 만한 숏폼 아이템을 찾지 못했습니다.</p>';
            } else {
                items.forEach((item, index) => {
                    const card = document.createElement('div');
                    card.className = 'border border-slate-200 rounded-lg p-4 bg-slate-50';
                    const titleRow = document.createElement('div');
                    titleRow.className = 'flex justify-between items-start gap-2 mb-2';
                    const title = document.createElement('h3');
                    title.className = 'text-sm font-bold text-slate-800';
                    title.innerHTML = '<span class="text-indigo-600">' + (index + 1) + '.</span> ' + escapeHtml(item.original_keyword || '');
                    const searchBtn = document.createElement('button');
                    searchBtn.type = 'button';
                    searchBtn.className = 'bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium py-2 px-3 rounded-lg transition-colors shrink-0';
                    searchBtn.textContent = '이 키워드로 쿠팡 검색';
                    searchBtn.addEventListener('click', () => searchCoupangFromAI(item.coupang_search_query || ''));
                    titleRow.appendChild(title);
                    titleRow.appendChild(searchBtn);
                    card.appendChild(titleRow);
                    const reasonP = document.createElement('p');
                    reasonP.className = 'text-sm text-slate-600 mb-2';
                    reasonP.innerHTML = '<span class="font-medium text-slate-700">AI 추천 사유:</span> ' + escapeHtml(item.reason || '');
                    card.appendChild(reasonP);
                    const queryP = document.createElement('p');
                    queryP.className = 'text-xs text-slate-500';
                    queryP.innerHTML = '쿠팡 최적화 검색어: <span class="bg-slate-200 text-slate-700 px-2 py-0.5 rounded">' + escapeHtml(item.coupang_search_query || '') + '</span>';
                    card.appendChild(queryP);
                    contentDiv.appendChild(card);
                });
            }
            document.getElementById('ai-curation-modal').classList.remove('hidden');
            document.body.classList.add('overflow-hidden');
        }

        function searchCoupangFromAI(searchQuery) {
            closeAIModal();
            if (searchKeyword) {
                searchKeyword.value = searchQuery;
                doSearch();
            }
        }

        function closeAIModal() {
            document.getElementById('ai-curation-modal').classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
        }

        // 💡 AI 추천 결과를 히스토리 시트로 수동 전송하는 함수
        async function saveCuratedHistory() {
            if (!cachedCurationData || cachedCurationData.length === 0) {
                alert("저장할 데이터가 없습니다.");
                return;
            }

            const btn = document.getElementById('btn-save-ai-history');
            const channelId = channelSelect.value;
            const customPrompt = document.getElementById('aiCustomPrompt').value.trim() || "기본 추천";

            btn.disabled = true;
            btn.innerHTML = '⏳ 저장 중...';

            try {
                const result = await apiPostJson('/ai/curate/send-to-history-sheet', {
                        channel_id: channelId,
                        custom_prompt: customPrompt,
                        items: cachedCurationData
                    });
                showStatus('저장 완료', result.message, 'success');
                btn.innerHTML = '✅ 저장 완료';
                btn.classList.add('opacity-50', 'cursor-not-allowed');
                btn.onclick = null;
            } catch (error) {
                alert("기록 저장 에러: " + error.message);
                btn.disabled = false;
                btn.innerHTML = '💾 이 추천 결과 기록장에 저장';
            }
        }

        document.getElementById('ai-curation-close').addEventListener('click', closeAIModal);

        window.closeStatusModal = closeStatusModal;
        window.runAICuration = runAICuration;
        window.openLastAIModal = openLastAIModal;
        window.changeStatus = changeStatus;
        window.saveCuratedHistory = saveCuratedHistory;

        loadChannels();

})();
