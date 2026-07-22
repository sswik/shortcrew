/**
 * 공개 몰: 상품 / 소개 탭 패널 표시.
 * 탭은 `<a href="/{slug}">`, `/{slug}/introduce` 로 실제 이동.
 * 서버 `data-initial-tab`·URL과 패널 `hidden` 을 맞춘 뒤, 히어로 소개 2줄 초과 시에만「더보기」노출.
 */
(function () {
    function tabFromUrlPath(slug) {
        var parts = window.location.pathname.split("/").filter(Boolean);
        if (!slug || !parts.length || parts[0] !== slug) {
            return "products";
        }
        if (parts.length === 1) {
            return "products";
        }
        if (parts.length === 2 && parts[1] === "introduce") {
            return "channel";
        }
        return "products";
    }

    function setActive(name) {
        var tabs = document.querySelectorAll("[data-shop-tab]");
        var panels = document.querySelectorAll("[data-shop-panel]");
        tabs.forEach(function (tab) {
            var on = tab.getAttribute("data-shop-tab") === name;
            tab.setAttribute("aria-selected", on ? "true" : "false");
            tab.tabIndex = on ? 0 : -1;
        });
        panels.forEach(function (panel) {
            var on = panel.getAttribute("data-shop-panel") === name;
            if (on) {
                panel.removeAttribute("hidden");
            } else {
                panel.setAttribute("hidden", "");
            }
        });
    }

    function initHeroBioMore() {
        var bio = document.querySelector(".shop-hero__bio.shop-hero__bio--clamp");
        var more = document.getElementById("shop-hero-more");
        if (!bio || !more) {
            return;
        }
        function measure() {
            if (bio.scrollHeight > bio.clientHeight + 2) {
                more.removeAttribute("hidden");
            } else {
                more.setAttribute("hidden", "");
            }
        }
        requestAnimationFrame(function () {
            requestAnimationFrame(measure);
        });
    }

    function init() {
        var wrap = document.querySelector("[data-shop-tabs]");
        if (!wrap) {
            return;
        }

        var slug = (wrap.getAttribute("data-shop-public-slug") || "").trim();
        var initialAttr = (wrap.getAttribute("data-initial-tab") || "").trim();
        var initial = initialAttr || tabFromUrlPath(slug);
        setActive(initial);

        initHeroBioMore();

        window.addEventListener("popstate", function () {
            if (!slug) {
                return;
            }
            setActive(tabFromUrlPath(slug));
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
