/**
 * 클릭 로그 계약(변경 시 shop-products.js·백오피스 리포트와 동시 검증):
 * - 트리거: `[data-track-click]` (캡처 단계)
 * - 필드: pump_slug, product_id, product_name?, deep_link?, review_id?
 * - 접속 정보(선택): client_user_agent, page_url, referrer_snapshot → /admin/logs 표시용
 */
function sendClickFromButton(button) {
    const pumpSlug = button.getAttribute("data-pump");
    if (!pumpSlug) {
        return;
    }
    const productIdRaw = button.getAttribute("data-product-id");
    const productId = productIdRaw === null || productIdRaw === undefined || productIdRaw === "" ? "0" : String(productIdRaw);
    const reviewId = button.getAttribute("data-review-id");
    const productName = button.getAttribute("data-product-name");
    const deepLink = button.getAttribute("data-deep-link") || button.getAttribute("href") || "";

    const body = new FormData();
    body.append("pump_slug", pumpSlug);
    body.append("product_id", productId);
    if (reviewId) body.append("review_id", String(reviewId));
    if (productName) body.append("product_name", String(productName));
    if (deepLink) body.append("deep_link", String(deepLink));
    try {
        if (typeof navigator !== "undefined" && navigator.userAgent) {
            body.append("client_user_agent", String(navigator.userAgent).slice(0, 512));
        }
        if (typeof location !== "undefined" && location.href) {
            body.append("page_url", String(location.href).slice(0, 800));
        }
        if (typeof document !== "undefined" && document.referrer) {
            body.append("referrer_snapshot", String(document.referrer).slice(0, 600));
        }
    } catch (e) {
        /* ignore */
    }

    fetch("/api/click", {
        method: "POST",
        body,
        keepalive: true,
    }).catch(() => {
        // Tracking failure should not block user action.
    });
}

function bindClickTracking() {
    if (document.body.dataset.clickTrackBound === "1") {
        return;
    }
    document.body.dataset.clickTrackBound = "1";
    document.addEventListener(
        "click",
        (ev) => {
            const button = ev.target.closest("[data-track-click]");
            if (!button) return;
            sendClickFromButton(button);
        },
        true,
    );
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindClickTracking);
} else {
    bindClickTracking();
}
