/**
 * 공개 몰: 시트 웹앱 JSON + 쿠팡 이미지 워커.
 * 시트 B열(또는 JSON `category`) 기준 카테고리 필터·페이지네이션(모바일 8=2×4, 데스크톱 10=5×2).
 */
(function () {
    var allProducts = [];
    /** 쿠파스 «영상 속 번호 상품»(서버 app/client/mall_kupas.py, 번호 큰 것부터) */
    var kupasProducts = [];
    var currentPage = 1;
    var currentKeyword = "";
    /**
     * 삼성 인터넷 등: 주소창·visualViewport 로 window resize 가 매우 잦고, 너비가 720 근처에서 흔들리면
     * getPageSize 8↔10 이 반복되어 paint → img 재생성 → 로드 끊김·onerror 가 반복될 수 있음.
     * matchMedia(...).change 는 “모바일/데스크톱” 구간을 넘을 때만 발생(높이만 변할 때는 미발생).
     */
    var lastLayoutPageSize = -1;

    function getPageSize() {
        if (typeof window !== "undefined" && window.matchMedia) {
            /* docs/05: 모바일 5개/페이지(2열 그리드와 맞춤) */
            if (window.matchMedia("(max-width: 720px)").matches) return 5;
        }
        return 10;
    }
    /** "" 이면 전체 */
    var activeCategory = "";
    var ctx = {
        root: null,
        pager: null,
        categoryBar: null,
        workerBase: "",
        pumpSlug: "",
        partnersLptag: "",
        /** 쿠파스 채널: 기존 상품까지 «번호 카드» 디자인(서버 shop_page_config.kupasMode) */
        kupasMode: false,
    };

    function readConfig() {
        var el = document.getElementById("shop-page-config");
        if (!el || !el.textContent) return {};
        try {
            return JSON.parse(el.textContent);
        } catch (e) {
            return {};
        }
    }

    /** main.py `shop_page_config.theme` → CSS 변수(모바일 셸·카테고리 톤). */
    function applyThemeFromConfig(cfg) {
        var t = cfg && cfg.theme ? cfg.theme : {};
        var root = document.documentElement;
        if (t.background) root.style.setProperty("--mall-theme-bg", t.background);
        if (t.card) root.style.setProperty("--mall-theme-card", t.card);
        if (t.accent) root.style.setProperty("--mall-theme-accent", t.accent);
        if (t.textMain) root.style.setProperty("--mall-theme-text", t.textMain);
        if (t.textSub) root.style.setProperty("--mall-theme-text-sub", t.textSub);
        if (t.border) root.style.setProperty("--mall-theme-border", t.border);
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
            w = "https://image.short-mall.com";
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
        var kw = String(currentKeyword || "").trim().toLowerCase();
        if (!kw) return list;
        return list.filter(function (p) {
            if (pickName(p).toLowerCase().indexOf(kw) !== -1) return true;
            // 번호로도 검색: 숫자면 정확매칭("001"·"07"·"7" → 해당 번호)
            // 쿠파스 구역이 있으면 "7" 은 영상 번호(위 구역) 전용, 기존 상품은 "007" 처럼 0 으로 시작할 때만.
            if (kupasProducts.length && /^[1-9]\d*$/.test(kw)) return false;
            if (p.__no && /^\d+$/.test(kw)) {
                if (String(p.__no) === String(parseInt(kw, 10))) return true;
            }
            return false;
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

    function showSearchBar() {
        var sr = document.getElementById("shop-product-search");
        if (sr) sr.hidden = false;
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
        showSearchBar();
    }

    function bindSearchInput() {
        var input = document.getElementById("shop-product-search-input");
        if (!input || input.dataset.bound === "1") return;
        input.dataset.bound = "1";
        input.addEventListener("input", function () {
            currentKeyword = String(input.value || "").trim();
            currentPage = 1;
            paint();
        });
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

    function renderError(root, msg) {
        hideCategoryBar();
        root.classList.add("is-empty");
        root.innerHTML = '<p class="muted shop-empty-message">' + msg + "</p>";
        root.setAttribute("aria-busy", "false");
        var pg = ctx.pager;
        if (pg) {
            pg.innerHTML = "";
            pg.hidden = true;
        }
    }

    function attachBuyAttributes(el, link, pumpSlug, coupangId, productName) {
        el.href = link;
        el.target = "_blank";
        el.rel = "noopener";
        el.setAttribute("data-track-click", "");
        el.setAttribute("data-pump", pumpSlug);
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

    function renderCards(root, items, workerBase, pumpSlug, partnersLptag) {
        root.innerHTML = "";
        if (!items.length) {
            root.classList.add("is-empty");
            root.innerHTML = '<p class="muted shop-empty-message">표시할 상품이 없습니다.</p>';
            root.setAttribute("aria-busy", "false");
            return;
        }
        root.classList.remove("is-empty");
        var frag = document.createDocumentFragment();
        if (ctx.kupasMode) {
            items.forEach(function (p) {
                if (pickName(p) || pickDeepLink(p)) frag.appendChild(buildKupasCard(p, true));
            });
            root.appendChild(frag);
            root.setAttribute("aria-busy", "false");
            return;
        }
        items.forEach(function (p) {
            var name = pickName(p);
            var priceRaw = pickPrice(p);
            var imgSrc = pickImage(p);
            var rawLink = pickDeepLink(p);
            var link = withCoupangPartnerQuery(rawLink, partnersLptag);
            var category = pickCategory(p);
            if (!name && !link) return;

            var coupangId = link ? extractCoupangProductId(link) : "";
            var hasValidLink = !!link;
            var card = document.createElement(hasValidLink ? "a" : "div");
            card.className = "card card--product";
            if (hasValidLink) {
                attachBuyAttributes(card, link, pumpSlug, coupangId, name);
                card.addEventListener("click", function () {
                    window.dispatchEvent(
                        new CustomEvent("mall:product-click", {
                            detail: {
                                deepLink: link,
                                name: name,
                                price: priceRaw,
                                category: category,
                            },
                        }),
                    );
                });
            } else {
                card.className += " is-disabled";
            }

            var media = document.createElement("div");
            media.className = "product-card__media";
            media.appendChild(buildThumbFrame(imgSrc, workerBase, name));
            // 자동 큐레이션 번호(001..) — 카드 좌상단 배지. 쿠파스 구역이 있으면 같은 숫자가
            // 두 번 보이지 않게 기존 상품 배지는 숨긴다("007" 검색은 계속 동작).
            if (p.__no && !kupasProducts.length) {
                var noBadge = document.createElement("span");
                noBadge.className = "product-card__no";
                noBadge.textContent = ("000" + p.__no).slice(-3);
                media.appendChild(noBadge);
            }
            card.appendChild(media);

            // sample/malls/05-homecam-short-mall/js/components/product-card.js 패턴과 동일:
            // 텍스트 영역을 innerHTML로 한 번에 구성(상품명 → 가격 → 카테고리).
            var content = document.createElement("div");
            content.className = "product-card__content";
            var metaHtml =
                '<p class="product-card__meta">' +
                '<span class="price">' +
                formatPriceKo(priceRaw) +
                "</span>" +
                (category
                    ? '<span class="product-card__meta-sep" aria-hidden="true"> | </span><span class="product-card__category">' +
                      String(category) +
                      "</span>"
                    : "") +
                "</p>";
            content.innerHTML =
                '<h3>' +
                (name || "(이름 없음)") +
                "</h3>" +
                metaHtml;

            card.appendChild(content);
            frag.appendChild(card);
        });
        root.appendChild(frag);
        root.setAttribute("aria-busy", "false");
    }

    /* ---------- 쿠파스 «영상 속 번호 상품» 구역 ---------- */

    /** 검색창 아래·카테고리 위에 [영상 속 번호 상품] 구역과 [전체 상품] 제목을 1회 삽입. */
    function setupKupasSection() {
        if (document.getElementById("shop-kupas")) return;
        var anchor = ctx.categoryBar || ctx.root;
        if (!anchor || !anchor.parentNode) return;
        var sec = document.createElement("section");
        sec.id = "shop-kupas";
        sec.className = "kupas-section";
        sec.setAttribute("aria-label", "영상 속 번호 상품");
        var list = document.createElement("div");
        list.id = "shop-kupas-list";
        list.className = "kupas-section__list";
        sec.appendChild(list);
        anchor.parentNode.insertBefore(sec, anchor);
        if (allProducts.length) {
            var h2 = document.createElement("h2");
            h2.id = "shop-legacy-title";
            h2.className = "kupas-section__title kupas-section__title--legacy";
            h2.textContent = "전체 상품";
            anchor.parentNode.insertBefore(h2, anchor);
        }
    }

    function kupasFiltered() {
        var kw = String(currentKeyword || "").trim().toLowerCase();
        if (!kw) return kupasProducts;
        return kupasProducts.filter(function (p) {
            if (/^[1-9]\d*$/.test(kw)) return p.__no === parseInt(kw, 10);
            return pickName(p).toLowerCase().indexOf(kw) !== -1;
        });
    }

    /** 쿠팡 이미지만 워커 경유, 그 밖(공개 이미지 호스트)은 원본 그대로. */
    function kupasImageSrc(src) {
        var s = String(src || "").trim();
        if (!s) return "";
        var host = "";
        try {
            host = new URL(s, location.href).hostname.toLowerCase();
        } catch (e) {
            return s;
        }
        return host.indexOf("coupang") !== -1 ? imageSrcForDisplay(s, ctx.workerBase) : s;
    }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text !== undefined && text !== null) n.textContent = String(text);
        return n;
    }

    /**
     * «번호 카드». legacy=true 면 기존 상품(시트 순서 번호) — 위 구역과 같은 숫자가 두 번 보이지 않게
     * 쿠파스 상품이 있으면 번호 배지를 빼고, 특징 칩 자리에 카테고리를 쓴다.
     */
    function buildKupasCard(p, legacy) {
        var name = pickName(p);
        var link = withCoupangPartnerQuery(pickDeepLink(p), ctx.partnersLptag);
        var card = el("article", "kupas-card" + (legacy ? " kupas-card--legacy" : ""));
        if (!legacy) {
            card.id = "kupas-" + p.__no;
            card.setAttribute("data-no", String(p.__no));
        }

        if (p.__no && (!legacy || !kupasProducts.length)) {
            card.appendChild(el("div", "kupas-card__no", p.__no));
        } else {
            card.classList.add("kupas-card--no-badge");
        }

        var img = el("img", "kupas-card__img");
        img.alt = name || "상품";
        img.loading = "lazy";
        var src = kupasImageSrc(pickImage(p));
        if (src) img.src = src;
        else img.style.visibility = "hidden";
        card.appendChild(img);

        var body = el("div", "kupas-card__body");
        body.appendChild(el("div", "kupas-card__name", name || "(이름 없음)"));
        var feats = Array.isArray(p.features) ? p.features : [];
        if (!feats.length && legacy && pickCategory(p)) feats = [pickCategory(p)];
        if (feats.length) {
            var fw = el("div", "kupas-card__feats");
            feats.slice(0, 4).forEach(function (f) {
                fw.appendChild(el("span", "", f));
            });
            body.appendChild(fw);
        }
        var rc = parseInt(p.reviewCount, 10);
        var rating = Number(p.rating);
        if (rc > 0 && rating > 0) {
            var score = el("div", "kupas-card__score");
            score.appendChild(el("b", "", "★ " + rating.toFixed(1)));
            score.appendChild(document.createTextNode(" · 상품평 " + rc.toLocaleString("ko-KR") + "개"));
            body.appendChild(score);
        }
        card.appendChild(body);

        if (link) {
            var btn = el("a", "kupas-card__btn", "제품 확인하고 돈 벌기");
            attachBuyAttributes(btn, link, ctx.pumpSlug, extractCoupangProductId(link), name);
            btn.rel = "sponsored nofollow noopener";
            btn.setAttribute("data-kupas-no", String(p.__no));
            btn.addEventListener("click", function () {
                window.dispatchEvent(
                    new CustomEvent("mall:product-click", {
                        detail: { deepLink: link, name: name, price: "", category: pickCategory(p), no: p.__no },
                    }),
                );
            });
            card.appendChild(btn);
        }
        var vid = String(p.video || "").trim();
        if (vid) {
            var va = el("a", "kupas-card__vid", "이 상품이 나온 영상 보기");
            va.href = "https://youtube.com/shorts/" + encodeURIComponent(vid);
            va.target = "_blank";
            va.rel = "noopener";
            card.appendChild(va);
        }
        return card;
    }

    function paintKupas() {
        var sec = document.getElementById("shop-kupas");
        var list = document.getElementById("shop-kupas-list");
        if (!sec || !list) return;
        var items = kupasFiltered();
        list.innerHTML = "";
        if (!items.length) {
            var kw = String(currentKeyword || "").trim();
            if (/^[1-9]\d*$/.test(kw)) {
                list.appendChild(el("p", "kupas-section__empty", kw + "번 상품은 아직 공개 전이에요."));
                sec.hidden = false;
            } else {
                sec.hidden = !!kw;
            }
            return;
        }
        sec.hidden = false;
        var frag = document.createDocumentFragment();
        items.forEach(function (p) {
            frag.appendChild(buildKupasCard(p));
        });
        list.appendChild(frag);
    }

    /** 몰 주소 #7 → 7번 카드로 스크롤·강조(프로필 링크에서 번호로 바로 진입). */
    function focusKupasFromHash() {
        var h = String(location.hash || "").replace(/^#/, "");
        if (!/^[1-9]\d*$/.test(h) || !kupasProducts.length) return;
        var card = document.getElementById("kupas-" + parseInt(h, 10));
        if (!card) return;
        card.classList.add("is-hit");
        card.scrollIntoView({ block: "center" });
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
        if (kupasProducts.length) {
            paintKupas();
            var legacyTitle = document.getElementById("shop-legacy-title");
            var numberSearch = /^[1-9]\d*$/.test(String(currentKeyword || "").trim());
            if (legacyTitle) legacyTitle.hidden = numberSearch;
            if (numberSearch) {
                // "7" 은 영상 번호 검색 → 아래 그리드는 비움(“검색 결과 없음” 문구도 내지 않음).
                ctx.root.innerHTML = "";
                if (ctx.pager) {
                    ctx.pager.innerHTML = "";
                    ctx.pager.hidden = true;
                }
                return;
            }
            if (!allProducts.length) return;
        }
        var list = productsFiltered();

        if (list.length === 0 && allProducts.length > 0) {
            var msg = String(currentKeyword || "").trim()
                ? "검색어에 맞는 상품이 없습니다."
                : "이 카테고리에 표시할 상품이 없습니다.";
            ctx.root.classList.add("is-empty");
            ctx.root.innerHTML = '<p class="muted shop-empty-message">' + msg + "</p>";
            ctx.root.setAttribute("aria-busy", "false");
            syncCategoryPillsActive();
            if (ctx.pager) {
                ctx.pager.innerHTML = "";
                ctx.pager.hidden = true;
            }
            return;
        }

        var items = sliceForPageFrom(list);
        ctx.root.classList.remove("is-empty");
        renderCards(
            ctx.root,
            items,
            ctx.workerBase,
            ctx.pumpSlug,
            ctx.partnersLptag,
        );
        renderPagerFor(list);
        syncCategoryPillsActive();
    }

    function load() {
        var cfg = readConfig();
        applyThemeFromConfig(cfg);
        ctx.root = document.getElementById("shop-product-root");
        ctx.pager = document.getElementById("shop-product-pager");
        ctx.categoryBar = document.getElementById("shop-product-categories");
        var loading = document.getElementById("shop-loading");
        if (!ctx.root) return;
        showSearchBar();
        bindSearchInput();

        var fetchUrl = String(cfg.mallProductsFetchUrl || "").trim();
        var apiUrl = String(cfg.mallProductsApiUrl || "").trim();
        var channel = String(cfg.mallApiChannel || "").trim();
        ctx.workerBase = String(cfg.coupangImageWorkerBase || "").trim();
        ctx.pumpSlug = String(cfg.pumpSlug || "").trim();
        ctx.partnersLptag = String(cfg.coupangPartnersLptag || "").trim();
        ctx.kupasMode = !!cfg.kupasMode;
        if (ctx.kupasMode) ctx.root.classList.add("kupas-root");

        if (!fetchUrl) {
            if (!apiUrl) {
                if (loading) loading.remove();
                renderError(
                    ctx.root,
                    "이 펌프 몰에 연결된 시트 상품 API URL이 없습니다. " +
                        "`.env`에 CHANNEL_…_MALL_PRODUCTS_API_URL 또는 PRODUCT_DELIVERY_WEBAPP_URL 을 설정하세요.",
                );
                return;
            }
            if (!channel) {
                if (loading) loading.remove();
                renderError(ctx.root, "채널 ID가 비어 있어 상품 API 주소를 만들 수 없습니다.");
                return;
            }
            fetchUrl = buildProductsApiUrl(apiUrl, channel);
        }

        fetchUrl = String(fetchUrl || "").trim();
        if (fetchUrl) {
            if (/^\/\//.test(fetchUrl)) {
                fetchUrl =
                    (window.location && window.location.protocol
                        ? window.location.protocol
                        : "https:") + fetchUrl;
            } else if (fetchUrl.charAt(0) === "/") {
                fetchUrl = new URL(fetchUrl, window.location.origin).href;
            }
        }

        fetch(fetchUrl, { credentials: "omit" })
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
                if (loading) loading.remove();
                var list = normalizeList(data);
                // 쿠파스 «영상 속 번호 상품»(section=kupas, 번호=시트 A열)과 기존 상품을 나눈다.
                var kupas = [];
                var legacy = [];
                list.forEach(function (p) {
                    if (p && typeof p === "object" && p.section === "kupas") kupas.push(p);
                    else legacy.push(p);
                });
                kupas.forEach(function (p) {
                    p.__no = parseInt(p.no, 10) || 0;
                });
                // 기존 상품: 큐레이션 순서대로 자동 번호(001..). 시트 행 순서 바꾸면 번호도 따라 재정렬됨.
                legacy.forEach(function (p, i) {
                    if (p && typeof p === "object") p.__no = i + 1;
                });
                kupasProducts = kupas;
                allProducts = legacy;
                if (kupasProducts.length) setupKupasSection();
                currentPage = 1;
                activeCategory = "";
                currentKeyword = "";
                var si = document.getElementById("shop-product-search-input");
                if (si) si.value = "";
                if (!allProducts.length && kupasProducts.length) {
                    // 쿠파스 상품만 있는 채널: 위 구역만 보이고 아래 그리드는 비운다.
                    ctx.root.innerHTML = "";
                    ctx.root.setAttribute("aria-busy", "false");
                    hideCategoryBar();
                    bindSearchInput();
                    paintKupas();
                    focusKupasFromHash();
                    return;
                }
                if (!allProducts.length) {
                    initCategoryBar(); // 최소 "전체" pill은 보여서 상품 탭 UI가 비정상처럼 보이지 않게 유지
                    renderError(
                        ctx.root,
                        "표시할 상품이 없습니다. 시트에 행이 있는지·웹앱 응답 형식을 확인하세요.",
                    );
                    return;
                }
                initCategoryBar();
                bindSearchInput();
                lastLayoutPageSize = getPageSize();
                paint();
                focusKupasFromHash();
            })
            .catch(function (err) {
                if (loading) loading.remove();
                var m = err && err.message ? String(err.message) : String(err);
                renderError(
                    ctx.root,
                    "상품을 불러오지 못했습니다. " +
                        m +
                        " — 터미널에서 확인: curl -sS " +
                        JSON.stringify(
                            (typeof location !== "undefined" && location.origin
                                ? location.origin
                                : "") + fetchUrl,
                        ) +
                        " — `.env` CHANNEL_*_MALL_PRODUCTS_CHANNEL_PARAM 은 Apps Script가 쓰는 ?channel= 값(샘플 APPS_SCRIPT_CHANNEL)과 맞출 것.",
                );
            });
    }

    function bindLayoutModeListener() {
        if (typeof window === "undefined" || !window.matchMedia) return;
        var mq = window.matchMedia("(max-width: 720px)");
        var debounceTimer = null;
        function onMediaChange() {
            if (!ctx.root || !allProducts.length) return;
            if (debounceTimer) clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                debounceTimer = null;
                var ps = getPageSize();
                if (ps === lastLayoutPageSize) {
                    return;
                }
                lastLayoutPageSize = ps;
                var list = productsFiltered();
                clampPageFor(list);
                paint();
            }, 200);
        }
        if (mq.addEventListener) {
            mq.addEventListener("change", onMediaChange);
        } else if (mq.addListener) {
            mq.addListener(onMediaChange);
        }
        window.addEventListener("orientationchange", onMediaChange);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            load();
            bindLayoutModeListener();
        });
    } else {
        load();
        bindLayoutModeListener();
    }
})();
