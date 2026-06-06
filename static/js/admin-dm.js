(function () {
  "use strict";
  const API = "/admin/api/ops";
  const $ = (id) => document.getElementById(id);

  const channelSel = $("dmChannel");
  const addBtn = $("dmAddRule");
  const rulesList = $("dmRulesList");
  const editor = $("dmEditor");
  const editorTitle = $("dmEditorTitle");
  const ruleIdEl = $("dmRuleId");
  const nameEl = $("dmName");
  const keywordsEl = $("dmKeywords");
  const pubChk = $("dmPublicReply");
  const msgEl = $("dmMessage");
  const productSel = $("dmProduct");
  const mediaGrid = $("dmMediaGrid");
  const mediaArea = $("dmMediaArea");
  const nextNote = $("dmNextNote");

  let rulesCache = [];
  let targetMode = "specific";
  let media = { id: "", permalink: "", thumbnail: "" };

  const esc = (s) => { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; };
  const replyInputs = () => Array.from(document.querySelectorAll(".dm-reply"));

  function jget(url) {
    return fetch(url, { credentials: "same-origin", redirect: "manual" }).then((r) => (r.ok ? r.json() : Promise.reject(r)));
  }
  function jsend(method, url, body) {
    return fetch(url, {
      method, credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => (r.ok ? r.json() : Promise.reject(r)));
  }

  // ---- 채널 로드 ----
  jget(API + "/dm/channels").then((d) => {
    (d.channels || []).forEach((c) => {
      const o = document.createElement("option");
      o.value = c.channel_id;
      o.textContent = c.channel_id + " · " + (c.name || "") + (c.ig_username ? " (@" + c.ig_username + ")" : "");
      channelSel.appendChild(o);
    });
  }).catch(() => {});

  channelSel.addEventListener("change", () => {
    const cid = channelSel.value;
    addBtn.disabled = !cid;
    editor.classList.add("hidden");
    if (cid) { loadRules(cid); loadProducts(cid); }
    else { rulesList.textContent = "채널을 선택하세요."; }
  });

  // ---- 규칙 목록 ----
  function loadRules(cid) {
    rulesList.textContent = "불러오는 중…";
    jget(API + "/dm/rules?channel_id=" + encodeURIComponent(cid))
      .then((d) => { rulesCache = d.rules || []; renderRules(); })
      .catch(() => { rulesList.textContent = "규칙을 불러오지 못했습니다."; });
  }
  function renderRules() {
    if (!rulesCache.length) { rulesList.innerHTML = '<p class="text-slate-500">등록된 자동화가 없습니다.</p>'; return; }
    rulesList.innerHTML = "";
    rulesCache.forEach((r) => {
      const trig = r.trigger_type === "keyword" ? "키워드: " + (r.keywords || []).join(", ") : "모든 댓글";
      const post = r.target_mode === "next" ? (r.ig_media_id ? "다음글(연결됨)" : "다음 발행글 대기") : "게시물 지정";
      const div = document.createElement("div");
      div.className = "flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3";
      div.innerHTML =
        '<div class="min-w-0"><p class="font-semibold text-slate-900">' + esc(r.name || "(이름 없음)") +
        (r.active ? "" : ' <span class="text-xs text-slate-400">[비활성]</span>') + "</p>" +
        '<p class="truncate text-xs text-slate-500">' + esc(post) + " · " + esc(trig) + "</p></div>" +
        '<div class="flex shrink-0 gap-2">' +
        '<button data-edit="' + r.id + '" class="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50">수정</button>' +
        '<button data-del="' + r.id + '" class="rounded border border-red-300 px-2 py-1 text-xs text-red-600 hover:bg-red-50">삭제</button></div>';
      rulesList.appendChild(div);
    });
    rulesList.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => openEditor(rulesCache.find((x) => String(x.id) === b.dataset.edit))));
    rulesList.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => delRule(b.dataset.del)));
  }

  function delRule(id) {
    if (!confirm("이 자동화를 삭제할까요?")) return;
    jsend("DELETE", API + "/dm/rules/" + id).then(() => loadRules(channelSel.value)).catch(() => alert("삭제 실패"));
  }

  // ---- 상품 로드 ----
  function loadProducts(cid) {
    productSel.innerHTML = '<option value="">상품 불러오는 중…</option>';
    jget("/api/mall-products?channel_id=" + encodeURIComponent(cid)).then((data) => {
      const arr = Array.isArray(data) ? data : (data.products || data.items || []);
      productSel.innerHTML = '<option value="">-- 채널 상품에서 선택 --</option>';
      let count = 0;
      arr.forEach((p, i) => {
        const name = p.name || p.productName || p.title || p["상품명"] || ("상품 " + (i + 1));
        const link = p.deepLink || p.productUrl || p.link || "";
        if (!link) return;
        const o = document.createElement("option");
        o.value = link;
        o.dataset.title = name;
        o.textContent = name.length > 40 ? name.slice(0, 40) + "…" : name;
        productSel.appendChild(o);
        count++;
      });
      if (count === 0) {
        productSel.innerHTML = '<option value="">이 채널에 등록된 상품이 없습니다</option>';
      }
    }).catch(() => {
      productSel.innerHTML = '<option value="">상품을 불러오지 못했습니다 — 잠시 후 다시 시도</option>';
    });
  }

  // ---- 게시물(미디어) ----
  function setMode(mode) {
    targetMode = mode;
    document.querySelectorAll(".dm-mode-btn").forEach((b) => {
      const on = b.dataset.targetMode === mode;
      b.classList.toggle("bg-accent", on);
      b.classList.toggle("text-slate-900", on);
      b.classList.toggle("border-accent", on);
    });
    mediaArea.classList.toggle("hidden", mode !== "specific");
    nextNote.classList.toggle("hidden", mode !== "next");
  }

  $("dmLoadMedia").addEventListener("click", () => {
    const cid = channelSel.value; if (!cid) return;
    mediaGrid.innerHTML = '<p class="col-span-full text-xs text-slate-500">불러오는 중…</p>';
    jget(API + "/dm/media?channel_id=" + encodeURIComponent(cid)).then((d) => renderMedia(d.media || []))
      .catch(() => { mediaGrid.innerHTML = '<p class="col-span-full text-xs text-red-600">게시물을 불러오지 못했습니다(토큰/권한 확인).</p>'; });
  });

  function renderMedia(items) {
    mediaGrid.innerHTML = "";
    if (!items.length) { mediaGrid.innerHTML = '<p class="col-span-full text-xs text-slate-500">게시물이 없습니다.</p>'; return; }
    items.forEach((m) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "dm-media-cell relative aspect-square overflow-hidden rounded-lg border-2 border-transparent bg-slate-100";
      cell.dataset.id = m.id;
      cell.innerHTML = '<img src="' + esc(m.thumbnail || "") + '" alt="" class="h-full w-full object-cover" onerror="this.style.opacity=0.2">';
      cell.onclick = () => selectMedia(m, cell);
      mediaGrid.appendChild(cell);
    });
  }
  function selectMedia(m, cell) {
    media = { id: m.id || "", permalink: m.permalink || "", thumbnail: m.thumbnail || "" };
    mediaGrid.querySelectorAll(".dm-media-cell").forEach((c) => c.classList.remove("border-accent"));
    if (cell) cell.classList.add("border-accent");
  }

  // ---- 편집기 ----
  addBtn.addEventListener("click", () => openEditor(null));
  $("dmCancel").addEventListener("click", () => editor.classList.add("hidden"));

  function openEditor(rule) {
    editor.classList.remove("hidden");
    mediaGrid.innerHTML = "";
    media = { id: "", permalink: "", thumbnail: "" };
    if (!rule) {
      editorTitle.textContent = "새 자동화";
      ruleIdEl.value = "";
      nameEl.value = ""; keywordsEl.value = ""; msgEl.value = "";
      pubChk.checked = true;
      replyInputs().forEach((i) => (i.value = ""));
      productSel.value = "";
      setTrigger("keyword");
      setMode("specific");
    } else {
      editorTitle.textContent = "자동화 수정";
      ruleIdEl.value = rule.id;
      nameEl.value = rule.name || "";
      keywordsEl.value = (rule.keywords || []).join(", ");
      msgEl.value = rule.dm_message || "";
      pubChk.checked = !!rule.public_reply_enabled;
      const v = rule.public_reply_variants || [];
      replyInputs().forEach((i, idx) => (i.value = v[idx] || ""));
      setTrigger(rule.trigger_type || "keyword");
      setMode(rule.target_mode || "specific");
      if (rule.ig_media_id) media = { id: rule.ig_media_id, permalink: rule.media_permalink || "", thumbnail: rule.media_thumbnail || "" };
      // 저장된 상품 링크 반영
      if (rule.dm_link) {
        let opt = Array.from(productSel.options).find((o) => o.value === rule.dm_link);
        if (!opt) {
          opt = document.createElement("option");
          opt.value = rule.dm_link; opt.dataset.title = rule.dm_product_title || "(저장된 상품)";
          opt.textContent = rule.dm_product_title || rule.dm_link;
          productSel.appendChild(opt);
        }
        productSel.value = rule.dm_link;
      } else productSel.value = "";
    }
    updatePreview();
  }

  function setTrigger(t) {
    document.querySelectorAll('input[name="dmTrigger"]').forEach((r) => (r.checked = r.value === t));
    keywordsEl.classList.toggle("opacity-40", t !== "keyword");
    keywordsEl.disabled = t !== "keyword";
  }
  function currentTrigger() {
    const r = document.querySelector('input[name="dmTrigger"]:checked');
    return r ? r.value : "keyword";
  }

  document.querySelectorAll(".dm-mode-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.targetMode)));
  document.querySelectorAll('input[name="dmTrigger"]').forEach((r) => r.addEventListener("change", () => setTrigger(r.value)));
  [msgEl, productSel, pubChk].forEach((el) => el.addEventListener("input", updatePreview));
  productSel.addEventListener("change", updatePreview);
  replyInputs().forEach((i) => i.addEventListener("input", updatePreview));

  function updatePreview() {
    const variants = replyInputs().map((i) => i.value.trim()).filter(Boolean);
    $("dmPrevReply").textContent = pubChk.checked && variants.length ? variants[0] : "(공개 답글 없음)";
    let dm = msgEl.value.trim() || "(DM 본문 없음)";
    const link = productSel.value || "";
    if (link) dm += "\n" + link;
    $("dmPrevDm").textContent = dm;
  }

  // ---- 저장 ----
  $("dmSave").addEventListener("click", () => {
    const cid = channelSel.value;
    if (!cid) { alert("채널을 선택하세요."); return; }
    if (targetMode === "specific" && !media.id) { alert("게시물을 선택하세요(또는 '다음 발행 게시물 자동')."); return; }
    const trigger = currentTrigger();
    const keywords = trigger === "keyword" ? keywordsEl.value.split(",").map((s) => s.trim()).filter(Boolean) : [];
    if (trigger === "keyword" && !keywords.length) { alert("키워드를 입력하거나 '모든 댓글'을 선택하세요."); return; }
    const opt = productSel.options[productSel.selectedIndex];
    const body = {
      channel_id: cid,
      name: nameEl.value.trim(),
      target_mode: targetMode,
      ig_media_id: targetMode === "specific" ? media.id : null,
      media_permalink: media.permalink || null,
      media_thumbnail: media.thumbnail || null,
      trigger_type: trigger,
      keywords: keywords,
      public_reply_enabled: pubChk.checked,
      public_reply_variants: replyInputs().map((i) => i.value.trim()).filter(Boolean),
      dm_message: msgEl.value,
      dm_link: productSel.value || "",
      dm_product_title: opt && opt.dataset ? opt.dataset.title || "" : "",
      dm_product_ref: opt && opt.dataset ? opt.dataset.title || "" : "",
      active: true,
    };
    const id = ruleIdEl.value;
    const p = id ? jsend("PATCH", API + "/dm/rules/" + id, body) : jsend("POST", API + "/dm/rules", body);
    p.then(() => { editor.classList.add("hidden"); loadRules(cid); }).catch(() => alert("저장 실패"));
  });
})();
