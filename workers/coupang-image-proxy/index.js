/**
 * 쿠팡 썸네일 프록시 (Cloudflare Workers).
 * 배포: 이 디렉터리에서 wrangler deploy 하거나 대시보드에 동일 로직 반영.
 * 운영 기본 베이스: COUPANG_IMAGE_WORKER_BASE / main.py _DEFAULT_COUPANG_IMAGE_WORKER (예: https://image.shortcrew.co.kr/)
 */
export default {
    async fetch(request) {
        if (request.method === "OPTIONS") {
            return new Response(null, {
                status: 204,
                headers: corsHeaders(),
            });
        }

        const url = new URL(request.url);

        let targetUrl = "";
        const bParam = url.searchParams.get("b");
        if (bParam) {
            targetUrl = decodeTargetFromBase64(bParam);
        }
        if (!targetUrl) {
            targetUrl = url.searchParams.get("url") || "";
            if (targetUrl) {
                targetUrl = targetUrl.replaceAll(":||", "://");
            }
        }
        if (!targetUrl) {
            let raw = url.pathname.slice(1) + url.search;
            raw = raw.replace(/^https:\/([^/])/, "https://$1");
            raw = raw.replace(/^http:\/([^/])/, "http://$1");
            targetUrl = raw;
        }

        if (!targetUrl || targetUrl === "" || targetUrl === "/") {
            return new Response(
                "운영자님, 워커는 응답 중입니다! 하지만 배달할 주소가 없어요.",
                {
                    headers: {
                        "Content-Type": "text/plain; charset=utf-8",
                        ...corsHeaders(),
                    },
                },
            );
        }

        if (targetUrl.startsWith("http") === false) {
            targetUrl = "https://" + targetUrl;
        }

        try {
            const response = await fetch(targetUrl, {
                headers: {
                    "User-Agent":
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
                    Referer: "https://www.coupang.com/",
                },
            });

            const body = await response.arrayBuffer();

            return new Response(body, {
                status: response.status,
                headers: {
                    "Access-Control-Allow-Origin": "*",
                    "Cross-Origin-Resource-Policy": "cross-origin",
                    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                    "Content-Type":
                        response.headers.get("Content-Type") || "image/jpeg",
                    "Cache-Control": "public, max-age=86400",
                },
            });
        } catch (e) {
            const msg = e && e.message ? String(e.message) : String(e);
            return new Response("이미지 배달 실패: " + msg, {
                status: 500,
                headers: { "Content-Type": "text/plain; charset=utf-8", ...corsHeaders() },
            });
        }
    },
};

/** `btoa(s)`(ASCII) 또는 `btoa(unescape(encodeURIComponent(s)))`(UTF-8) 모두 복원 */
function decodeTargetFromBase64(bParam) {
    try {
        const bin = atob(bParam);
        const t = bin.trim();
        if (/^https?:\/\//i.test(t)) return t;
        const len = bin.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i) & 0xff;
        return new TextDecoder("utf-8").decode(bytes);
    } catch {
        return "";
    }
}

function corsHeaders() {
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "86400",
        "Cross-Origin-Resource-Policy": "cross-origin",
    };
}
