/**
 * 리뷰 폼: 인플루언서 변경 시 시트 `게시중` + DB 매칭 상품으로 연결 상품 옵션 갱신.
 */
(function () {
  const infSel = document.getElementById("review-influencer");
  const prodSel = document.getElementById("review-product");
  const sheetTitleEl = document.getElementById("review-sheet-product-title");
  const sheetDeeplinkEl = document.getElementById("review-sheet-product-deeplink");
  if (!infSel || !prodSel) {
    return;
  }

  function syncSheetHiddenFromSelect() {
    if (!sheetTitleEl || !sheetDeeplinkEl) return;
    const opt = prodSel.selectedOptions[0];
    if (!opt || !opt.value) {
      sheetTitleEl.value = "";
      sheetDeeplinkEl.value = "";
      return;
    }
    const pid = parseInt(opt.value, 10);
    if (!Number.isFinite(pid) || pid < 0) {
      sheetTitleEl.value = opt.getAttribute("data-sheet-title") || "";
      sheetDeeplinkEl.value = (opt.getAttribute("data-deeplink") || "").trim();
    } else {
      sheetTitleEl.value = "";
      sheetDeeplinkEl.value = "";
    }
  }

  async function refreshProductOptions() {
    const slug = infSel.value;
    const prev = prodSel.value;
    const form = document.getElementById("review-admin-form");
    const reviewId =
      form && form.getAttribute("data-review-id")
        ? String(form.getAttribute("data-review-id")).trim()
        : "";
    let url =
      "/admin/reviews/product-options?influencer_slug=" + encodeURIComponent(slug);
    if (prev) {
      url +=
        "&selected_product_id=" + encodeURIComponent(String(prev));
    }
    if (reviewId) {
      url += "&review_id=" + encodeURIComponent(reviewId);
    }
    let data;
    try {
      const r = await fetch(url, { credentials: "same-origin" });
      if (!r.ok) {
        throw new Error("HTTP " + r.status);
      }
      data = await r.json();
    } catch (e) {
      console.error("product-options", e);
      return;
    }
    const items = Array.isArray(data.items) ? data.items : [];
    prodSel.innerHTML = '<option value="">선택 안 함</option>';
    for (let i = 0; i < items.length; i += 1) {
      const it = items[i];
      const o = document.createElement("option");
      o.value = String(it.id);
      o.textContent = it.title || String(it.id);
      if (it.deeplink) {
        o.setAttribute("data-deeplink", String(it.deeplink));
      }
      const idNum = Number(it.id);
      if (Number.isFinite(idNum) && idNum < 0 && it.sheet_title) {
        o.setAttribute("data-sheet-title", String(it.sheet_title));
      }
      prodSel.appendChild(o);
    }
    const keep = items.some(function (it) {
      return String(it.id) === prev;
    });
    prodSel.value = keep ? prev : "";
    syncSheetHiddenFromSelect();
  }

  infSel.addEventListener("change", refreshProductOptions);
  prodSel.addEventListener("change", syncSheetHiddenFromSelect);
  /* 서버 렌더와 동일 소스로 한 번 더 채움(배포 직후·캐시 등) */
  refreshProductOptions();
  syncSheetHiddenFromSelect();
})();
