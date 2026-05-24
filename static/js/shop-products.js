/**
 * 공개 몰: 시트 웹앱 JSON + 쿠팡 이미지 워커.
 * 시트 B열(또는 JSON `category`) 기준 카테고리·상품명 검색 필터·페이지네이션(20개/페이지).
 */
(function () {
    var allProducts = [];
    var currentPage = 1;
    var PRODUCTS_CACHE_NS = "products";
    var PRODUCTS_CACHE_TTL_MS = 120 * 1000;
    var DEFAULT_PRODUCTS_PER_PAGE = 20;

    function getPageSize() {
        var cfg = readConfig();
        var n = parseInt(cfg && cfg.productsPerPage, 10);
        return n > 0 ? n : DEFAULT_PRODUCTS_PER_PAGE;
    }
    /** "" 이면 전체 */
    var activeCategory = "";
    var searchQuery = "";
    var searchDebounceTimer = null;
    var ctx = {
        root: null,
        pager: null,
        categoryBar: null,
        workerBase: "",
        influencerSlug: "",
        mallApiChannel: "",
        partnersLptag: "",
    };

    function debugCache(eventName, extra) {
        try {
            if (typeof console !== "undefined" && console.debug) {
                console.debug("[shop-products-cache]", eventName, extra || {});
            }
        } catch (e) {}
    }

    function readConfig() {
        var el = document.getElementById("shop-page-config");
        if (!el || !el.textContent) return {};
        try {
            return JSON.parse(el.textContent);
        } catch (e) {
            return {};
        }
    }

    function buildProductsApiUrl(apiUrl, channel) {
        apiUrl = String(apiUrl || "").trim();
        channel = String(channel || "").trim();
        if (!apiUrl || !channel) return "";
        var sep = apiUrl.indexOf("?") === -1 ? "?" : "&";
        return apiUrl + sep + "channel=" + encodeURIComponent(channel);
    }

    function normalizeList(data) {
        if (Array.isArray(data)) return data;
        if (data && Array.isArray(data.items)) return data.items;
        if (data && Array.isArray(data.products)) return data.products;
        return [];
    }

    function canUseSessionStorage() {
        try {
            if (typeof window === "undefined" || !window.sessionStorage) return false;
            var k = "__shop_products_cache_test__";
            window.sessionStorage.setItem(k, "1");
            window.sessionStorage.removeItem(k);
            return true;
        } catch (e) {
            return false;
        }
    }

    function productsCacheKey(fetchUrl) {
        var slug = String(ctx.influencerSlug || "").trim();
        var channel = String(ctx.mallApiChannel || "").trim();
        if (slug && channel) return PRODUCTS_CACHE_NS + ":" + slug + ":" + channel;
        return PRODUCTS_CACHE_NS + ":url:" + String(fetchUrl || "").trim();
    }

    function readProductsSessionCache(key) {
        if (!canUseSessionStorage() || !key) return { state: "unavailable", items: [] };
        var raw = "";
        try {
            raw = String(window.sessionStorage.getItem(key) || "");
        } catch (e1) {
            return { state: "unavailable", items: [] };
        }
        if (!raw) return { state: "miss", items: [] };
        try {
            var parsed = JSON.parse(raw);
            var ts = Number(parsed && parsed.ts ? parsed.ts : 0);
            var items = parsed && Array.isArray(parsed.items) ? parsed.items : null;
            if (!items || !ts) return { state: "invalid", items: [] };
            if (Date.now() - ts > PRODUCTS_CACHE_TTL_MS) return { state: "stale", items: items };
            return { state: "hit", items: items };
        } catch (e2) {
            return { state: "invalid", items: [] };
        }
    }

    function writeProductsSessionCache(key, items) {
        if (!canUseSessionStorage() || !key || !Array.isArray(items) || !items.length) return;
        try {
            window.sessionStorage.setItem(
                key,
                JSON.stringify({
                    ts: Date.now(),
                    items: items,
                }),
            );
        } catch (e) {}
    }

    function productsFingerprint(list) {
        if (!Array.isArray(list) || !list.length) return "0";
        var max = Math.min(list.length, 12);
        var sig = [];
        for (var i = 0; i < max; i += 1) {
            var p = list[i] || {};
            sig.push(
                [
                    pickName(p),
                    pickPrice(p),
                    pickImage(p),
                    pickDeepLink(p),
                    pickCategory(p),
                ].join("|"),
            );
        }
        return String(list.length) + ":" + sig.join("||");
    }

    function pickName(p) {
        return String(p.name || p.productName || p.title || p.상품명 || "").trim();
    }

    function pickPrice(p) {
        var v = p.price;
        if (v === undefined || v === null) return "";
        return String(v).trim();
    }

    function pickImage(p) {
        return String(p.image || p.imageUrl || p.thumbnail || "").trim();
    }

    /**
     * 워커 썸네일: `?b=` Base64·`_cb=` 캐시버스트는 일부 광고차단 휴리스틱에 걸리기 쉬움.
     * `?url=` + 평문에 가까운 값(스킴만 `://` → `:||` 치환, Worker에서 복구) — 구형 `?b=` 는 Worker가 계속 지원.
     */
    function imageSrcForDisplay(imgSrc, workerBase) {
        var s = String(imgSrc || "").trim();
        if (!s) return "";
        if (/^data:/i.test(s) || /^blob:/i.test(s)) return s;
        var safeUrl = s;
        if (/^\/\//.test(safeUrl)) safeUrl = "https:" + safeUrl;
        safeUrl = safeUrl.replace("://", ":||");

        var w = String(workerBase || "").trim();
        if (!w) {
            w = "https://image.shortcrew.co.kr";
        }
        w = w.replace(/\/?$/, "");
        return w + "/?url=" + encodeURIComponent(safeUrl);
    }

    function pickDeepLink(p) {
        return String(p.deepLink || p.productUrl || p.link || "").trim();
    }

    /** 시트 B열·웹앱 JSON `category` 등 */
    function pickCategory(p) {
        return String(p.category || p.카테고리 || p.cat || p.categoryName || "").trim();
    }

    function productsInCategory() {
        if (!activeCategory) return allProducts;
        return allProducts.filter(function (p) {
            return pickCategory(p) === activeCategory;
        });
    }

    function productsFiltered() {
        var list = productsInCategory();
        var q = String(searchQuery || "")
            .trim()
            .toLowerCase();
        if (!q) return list;
        return list.filter(function (p) {
            var name = pickName(p).toLowerCase();
            var cat = pickCategory(p).toLowerCase();
            return name.indexOf(q) !== -1 || cat.indexOf(q) !== -1;
        });
    }

    function uniqueSortedCategories(products) {
        var seen = {};
        var out = [];
        products.forEach(function (p) {
            var c = pickCategory(p);
            if (!c || seen[c]) return;
            seen[c] = true;
            out.push(c);
        });
        out.sort(function (a, b) {
            return a.localeCompare(b, "ko");
        });
        return out;
    }

    function hideCategoryBar() {
        var bar = ctx.categoryBar;
        if (!bar) return;
        bar.innerHTML = "";
        bar.hidden = true;
    }

    function syncCategoryPillsActive() {
        var bar = ctx.categoryBar;
        if (!bar || bar.hidden) return;
        var pills = bar.querySelectorAll(".shop-product-categories__pill");
        pills.forEach(function (btn) {
            var isAll = btn.getAttribute("data-all") === "1";
            var cat = isAll ? "" : String(btn.getAttribute("data-category") || "");
            btn.classList.toggle("is-active", cat === activeCategory);
            btn.setAttribute("aria-pressed", cat === activeCategory ? "true" : "false");
        });
    }

    function initCategoryBar() {
        var bar = ctx.categoryBar;
        if (!bar) return;
        var cats = uniqueSortedCategories(allProducts);
        bar.innerHTML = "";
        var inner = document.createElement("div");
        inner.className = "shop-product-categories__inner";

        function addPill(label, categoryValue, isAll) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "shop-product-categories__pill";
            b.textContent = label;
            if (isAll) {
                b.setAttribute("data-all", "1");
            } else {
                b.setAttribute("data-category", categoryValue);
            }
            b.setAttribute("aria-pressed", activeCategory === categoryValue ? "true" : "false");
            if (activeCategory === categoryValue) b.classList.add("is-active");
            b.addEventListener("click", function () {
                activeCategory = categoryValue;
                currentPage = 1;
                syncCategoryPillsActive();
                paint();
            });
            inner.appendChild(b);
        }

        addPill("전체", "", true);
        cats.forEach(function (c) {
            addPill(c, c, false);
        });
        bar.appendChild(inner);
        bar.hidden = false;
    }

    /** 쿠팡 도메인이면 URL에 lptag 쿼리를 붙인다(이미 있으면 덮어쓰지 않음). */
    function withCoupangPartnerQuery(url, lptag) {
        var u = String(url || "").trim();
        if (!u) return "";
        var lp = String(lptag || "").trim();
        if (!lp) return u;
        var parsed;
        try {
            parsed = new URL(u, "https://www.coupang.com");
        } catch (e) {
            return u;
        }
        var host = (parsed.hostname || "").toLowerCase();
        if (host.indexOf("coupang.com") === -1) return u;
        try {
            if (!parsed.searchParams.get("lptag")) parsed.searchParams.set("lptag", lp);
            return parsed.href;
        } catch (e2) {
            return u;
        }
    }

    function formatPriceKo(raw) {
        var s = String(raw || "");
        var digits = s.replace(/[^\d]/g, "");
        if (!digits) return s || "";
        return Number(digits).toLocaleString("ko-KR") + "원";
    }

    function extractCoupangProductId(url) {
        try {
            var u = new URL(url, "https://www.coupang.com");
            var m = u.pathname.match(/\/vp\/products\/(\d+)/);
            if (m && m[1]) return m[1];
            var c = u.searchParams.get("ctag");
            return c || "";
        } catch (e) {
            return "";
        }
    }

    var SHOP_EMPTY_MSG = "등록된 상품이 없습니다";

    function logProductsLoadError(err, fetchUrl, cfg) {
        try {
            if (typeof console !== "undefined" && console.error) {
                console.error("[shop-products] load failed", {
                    message: err && err.message ? String(err.message) : String(err),
                    fetchUrl: fetchUrl,
                    apiUrl: cfg && cfg.mallProductsApiUrl,
                    channel: cfg && cfg.mallApiChannel,
                });
            }
        } catch (e) {}
    }

    function renderShopEmpty(root) {
        hideCategoryBar();
        root.innerHTML =
            '<p class="shop-products-empty muted">' + SHOP_EMPTY_MSG + "</p>";
        root.setAttribute("aria-busy", "false");
        var pg = ctx.pager;
        if (pg) {
            pg.innerHTML = "";
            pg.hidden = true;
        }
    }

    function attachBuyAttributes(el, link, influencerSlug, coupangId, productName) {
        el.href = link;
        el.target = "_blank";
        el.rel = "noopener";
        el.setAttribute("data-track-click", "");
        el.setAttribute("data-influencer", influencerSlug);
        el.setAttribute("data-product-id", coupangId || "0");
        if (link) el.setAttribute("data-deep-link", String(link));
        if (productName) el.setAttribute("data-product-name", String(productName));
    }

    /**
     * short-mall-template 과 동일: 썸네일은 `<a>` 직속 `<img>`가 아니라 `div`(고정 비율·flex 중앙) 안의 `<img>`.
     * 삼성 인터넷 등에서 링크-이미지 직결합 레이아웃/로드 이슈를 피하기 위함.
     */
    function buildThumbFrame(imgSrc, workerBase, name) {
        var frame = document.createElement("div");
        frame.className = "product-card__media-frame";

        var img = document.createElement("img");
        img.className = "product-image";
        img.alt = name || "상품";
        img.loading = "lazy"; // eager보다 lazy가 모바일 커넥션 병목 방지에 유리합니다.

        if (imgSrc) {
            var baseSrc = imageSrcForDisplay(imgSrc, workerBase);
            img.src = baseSrc;

            img.onerror = function () {
                // 절대 img.removeAttribute("src")를 쓰지 마세요(삼성 인터넷 등).
                if (!img.dataset.retried) {
                    img.dataset.retried = "true";
                    setTimeout(function () {
                        img.src = baseSrc;
                    }, 300);
                } else {
                    img.style.opacity = "0.1";
                }
            };
        } else {
            img.style.display = "none";
        }

        frame.appendChild(img);
        return frame;
    }

    function renderCards(root, items, workerBase, influencerSlug, partnersLptag) {
        root.innerHTML = "";
        if (!items.length) {
            root.innerHTML =
                '<p class="shop-products-empty muted">' + SHOP_EMPTY_MSG + "</p>";
            root.setAttribute("aria-busy", "false");
            return;
        }
        var frag = document.createDocumentFragment();
        items.forEach(function (p) {
            var name = pickName(p);
            var priceRaw = pickPrice(p);
            var imgSrc = pickImage(p);
            var rawLink = pickDeepLink(p);
            var link = withCoupangPartnerQuery(rawLink, partnersLptag);
            if (!name && !link) return;

            var card = document.createElement("article");
            card.className = "card card--product";

            var coupangId = link ? extractCoupangProductId(link) : "";

            if (link) {
                var media = document.createElement("a");
                media.className = "product-card__media";
                attachBuyAttributes(media, link, influencerSlug, coupangId, name);
                media.appendChild(buildThumbFrame(imgSrc, workerBase, name));
                card.appendChild(media);
            } else {
                var wrap = document.createElement("div");
                wrap.className = "product-card__media";
                wrap.appendChild(buildThumbFrame(imgSrc, workerBase, name));
                card.appendChild(wrap);
            }

            var h = document.createElement("h3");
            h.textContent = name || "(이름 없음)";
            card.appendChild(h);

            var pr = document.createElement("p");
            pr.className = "price";
            pr.textContent = formatPriceKo(priceRaw);
            card.appendChild(pr);

            var a = document.createElement("a");
            a.className = "btn btn-primary";
            a.textContent = "바로 구매하기";
            if (link) {
                attachBuyAttributes(a, link, influencerSlug, coupangId, name);
            } else {
                a.href = "#";
                a.className += " disabled";
                a.setAttribute("aria-disabled", "true");
            }
            card.appendChild(a);
            frag.appendChild(card);
        });
        root.appendChild(frag);
        root.setAttribute("aria-busy", "false");
    }

    function totalPagesFor(list) {
        var n = list.length;
        var ps = getPageSize();
        return Math.max(1, Math.ceil(n / ps));
    }

    function clampPageFor(list) {
        var tp = totalPagesFor(list);
        if (currentPage > tp) currentPage = tp;
        if (currentPage < 1) currentPage = 1;
    }

    function sliceForPageFrom(list) {
        clampPageFor(list);
        var ps = getPageSize();
        var start = (currentPage - 1) * ps;
        return list.slice(start, start + ps);
    }

    function renderPagerFor(list) {
        var pager = ctx.pager;
        if (!pager) return;
        var tp = totalPagesFor(list);
        if (list.length === 0 || tp <= 1) {
            pager.innerHTML = "";
            pager.hidden = true;
            return;
        }
        pager.hidden = false;
        pager.innerHTML = "";

        var prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "이전";
        prev.disabled = currentPage <= 1;
        prev.addEventListener("click", function () {
            if (currentPage > 1) {
                currentPage -= 1;
                paint();
            }
        });
        pager.appendChild(prev);

        for (var i = 1; i <= tp; i += 1) {
            (function (pageNum) {
                var b = document.createElement("button");
                b.type = "button";
                b.textContent = String(pageNum);
                if (pageNum === currentPage) b.className = "is-active";
                b.addEventListener("click", function () {
                    currentPage = pageNum;
                    paint();
                });
                pager.appendChild(b);
            })(i);
        }

        var next = document.createElement("button");
        next.type = "button";
        next.textContent = "다음";
        next.disabled = currentPage >= tp;
        next.addEventListener("click", function () {
            if (currentPage < tp) {
                currentPage += 1;
                paint();
            }
        });
        pager.appendChild(next);
    }

    function paint() {
        if (!ctx.root) return;
        var list = productsFiltered();

        if (list.length === 0 && allProducts.length > 0) {
            var emptyMsg = searchQuery.trim()
                ? "검색 결과가 없습니다."
                : "이 카테고리에 표시할 상품이 없습니다.";
            ctx.root.innerHTML =
                '<p class="shop-products-empty muted">' + emptyMsg + "</p>";
            ctx.root.setAttribute("aria-busy", "false");
            syncCategoryPillsActive();
            if (ctx.pager) {
                ctx.pager.innerHTML = "";
                ctx.pager.hidden = true;
            }
            return;
        }

        var items = sliceForPageFrom(list);
        renderCards(
            ctx.root,
            items,
            ctx.workerBase,
            ctx.influencerSlug,
            ctx.partnersLptag,
        );
        renderPagerFor(list);
        syncCategoryPillsActive();
    }

    function applyProductsAndRender(list, loading) {
        if (loading) loading.remove();
        allProducts = Array.isArray(list) ? list : [];
        currentPage = 1;
        activeCategory = "";
        searchQuery = "";
        var searchEl = document.getElementById("shop-product-search");
        if (searchEl) searchEl.value = "";
        if (!allProducts.length) {
            renderShopEmpty(ctx.root);
            return false;
        }
        initCategoryBar();
        paint();
        return true;
    }

    function fetchProductsJson(fetchUrl) {
        return fetch(fetchUrl, { credentials: "omit" })
            .then(function (res) {
                return res.text().then(function (text) {
                    if (!res.ok) {
                        var msg = "HTTP " + res.status;
                        try {
                            var j = JSON.parse(text);
                            if (j && j.detail) msg += ": " + String(j.detail);
                            else if (text) msg += ": " + text.slice(0, 400);
                        } catch (e1) {
                            if (text) msg += ": " + text.slice(0, 400);
                        }
                        throw new Error(msg);
                    }
                    try {
                        return JSON.parse(text);
                    } catch (e2) {
                        throw new Error(
                            "JSON 파싱 실패: " +
                                (text ? text.slice(0, 300) : "(빈 본문)") +
                                " — 웹앱이 배열/객체 JSON을 반환하는지 확인하세요.",
                        );
                    }
                });
            })
            .then(function (data) {
                return normalizeList(data);
            });
    }

    function load() {
        var cfg = readConfig();
        ctx.root = document.getElementById("shop-product-root");
        ctx.pager = document.getElementById("shop-product-pager");
        ctx.categoryBar = document.getElementById("shop-product-categories");
        var loading = document.getElementById("shop-loading");
        if (!ctx.root) return;

        var fetchUrl = String(cfg.mallProductsFetchUrl || "").trim();
        var apiUrl = String(cfg.mallProductsApiUrl || "").trim();
        var channel = String(cfg.mallApiChannel || "").trim();
        ctx.workerBase = String(cfg.coupangImageWorkerBase || "").trim();
        ctx.influencerSlug = String(cfg.influencerSlug || "").trim();
        ctx.mallApiChannel = String(cfg.mallApiChannel || "").trim();
        ctx.partnersLptag = String(cfg.coupangPartnersLptag || "").trim();

        if (!fetchUrl) {
            if (!apiUrl || !channel) {
                if (loading) loading.remove();
                logProductsLoadError(
                    new Error("mall products API not configured"),
                    "",
                    cfg,
                );
                renderShopEmpty(ctx.root);
                return;
            }
            fetchUrl = buildProductsApiUrl(apiUrl, channel);
        }

        fetchUrl = String(fetchUrl || "").trim();
        if (fetchUrl) {
            if (/^https?:\/\//i.test(fetchUrl)) {
                /* absolute URL — use as-is */
            } else if (/^\/\//.test(fetchUrl)) {
                fetchUrl =
                    (window.location && window.location.protocol
                        ? window.location.protocol
                        : "https:") + fetchUrl;
            } else if (fetchUrl.charAt(0) === "/") {
                fetchUrl = new URL(fetchUrl, window.location.origin).href;
            }
        }

        var cacheKey = productsCacheKey(fetchUrl);
        var cache = readProductsSessionCache(cacheKey);
        if (cache.state === "hit") {
            debugCache("cache_hit", { key: cacheKey, size: cache.items.length });
            applyProductsAndRender(cache.items, loading);
            var prevSig = productsFingerprint(cache.items);
            fetchProductsJson(fetchUrl)
                .then(function (networkList) {
                    if (!Array.isArray(networkList) || !networkList.length) return;
                    writeProductsSessionCache(cacheKey, networkList);
                    var nextSig = productsFingerprint(networkList);
                    if (nextSig !== prevSig) {
                        debugCache("revalidate_ok", { key: cacheKey, changed: true });
                        applyProductsAndRender(networkList, null);
                    } else {
                        debugCache("revalidate_ok", { key: cacheKey, changed: false });
                    }
                })
                .catch(function (err1) {
                    debugCache("revalidate_fail", {
                        key: cacheKey,
                        message: err1 && err1.message ? String(err1.message) : String(err1),
                    });
                });
            return;
        }

        if (cache.state === "stale") {
            debugCache("cache_stale", { key: cacheKey, size: cache.items.length });
        } else if (cache.state === "miss") {
            debugCache("cache_miss", { key: cacheKey });
        } else if (cache.state === "invalid") {
            debugCache("cache_invalid", { key: cacheKey });
        }

        fetchProductsJson(fetchUrl)
            .then(function (list) {
                var ok = applyProductsAndRender(list, loading);
                if (ok) writeProductsSessionCache(cacheKey, list);
            })
            .catch(function (err) {
                if (loading) loading.remove();
                logProductsLoadError(err, fetchUrl, cfg);
                renderShopEmpty(ctx.root);
            });
    }

    function bindSearchInput() {
        var el = document.getElementById("shop-product-search");
        if (!el) return;
        el.addEventListener("input", function () {
            if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(function () {
                searchDebounceTimer = null;
                searchQuery = el.value || "";
                currentPage = 1;
                paint();
            }, 200);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            load();
            bindSearchInput();
        });
    } else {
        load();
        bindSearchInput();
    }
})();
