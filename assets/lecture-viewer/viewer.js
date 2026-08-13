(() => {
  "use strict";

  const deck = window.DECK || (typeof DECK !== "undefined" ? DECK : null);
  const mount = document.querySelector("#lecture-viewer, [data-lecture-viewer]");

  if (!deck || !Array.isArray(deck.groups) || !mount) {
    console.error("Lecture Viewer needs a DECK object and a #lecture-viewer mount element.");
    return;
  }

  const icon = {
    previous: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 5-7 7 7 7M8 12h9"/></svg>',
    next: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 5 7 7-7 7M16 12H7"/></svg>',
    grid: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/></svg>',
    document: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h9l3 3V20.5H6zM9 11h6M9 15h6M9 7h2"/></svg>',
    fullscreen: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 4H4v4.5M15.5 4H20v4.5M20 15.5V20h-4.5M4 15.5V20h4.5"/></svg>',
    menu: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    collapse: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg>',
    close: '<svg class="viewer-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>'
  };

  const slides = [];
  const sections = [];
  deck.groups.forEach((group, groupIndex) => {
    (group.sections || []).forEach((section, sectionIndex) => {
      const sectionSlides = Array.isArray(section.slides) ? section.slides : [];
      const sectionRecord = { ...section, group, groupIndex, sectionIndex, start: slides.length, count: sectionSlides.length };
      sections.push(sectionRecord);
      sectionSlides.forEach((slide, slideIndex) => {
        slides.push({ ...slide, group, section: sectionRecord, groupIndex, sectionIndex, slideIndex });
      });
    });
  });

  if (!slides.length) {
    console.error("Lecture Viewer could not find any slides in DECK.groups.");
    return;
  }

  const storage = {
    get(key) {
      try { return window.localStorage.getItem(key); }
      catch (_) { return null; }
    },
    set(key, value) {
      try { window.localStorage.setItem(key, value); }
      catch (_) { /* Some file:// contexts intentionally do not expose storage. */ }
    }
  };

  const state = {
    current: 0,
    documentMode: false,
    gridOpen: false,
    drawerOpen: false,
    collapsed: storage.get("lecture-viewer:sidebar-collapsed") === "true",
    lastFocus: null,
    beforePrintDocumentMode: null
  };

  const escapeHTML = (value) => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");

  const inlineBold = (value) => escapeHTML(value)
    .replace(/&lt;b&gt;/gi, "<b>")
    .replace(/&lt;\/b&gt;/gi, "</b>");

  const safeHref = (href) => {
    const value = String(href || "").trim();
    return /^(https?:|mailto:|tel:|\/|\.\/|\.\.\/|#)/i.test(value) ? value : "#";
  };

  const slugFromHash = () => {
    try { return decodeURIComponent(window.location.hash.replace(/^#/, "")); }
    catch (_) { return window.location.hash.replace(/^#/, ""); }
  };

  const indexFromHash = () => slides.findIndex((slide) => slide.id === slugFromHash());

  const renderLinkAndCitations = (slide) => {
    const link = slide.link && slide.link.href
      ? `<a class="viewer-deep-link" href="${escapeHTML(safeHref(slide.link.href))}">${escapeHTML(slide.link.label || "연계 교재 보기")}</a>`
      : "";
    const citations = Array.isArray(slide.cite) && slide.cite.length
      ? `<div class="viewer-citations">${slide.cite.map((cite) => `<span>${escapeHTML(cite)}</span>`).join("")}</div>`
      : "";
    return link || citations ? `<footer class="viewer-slide-footer">${link}${citations}</footer>` : "";
  };

  const renderHeading = (slide, isCover = false) => `
    <header class="viewer-slide-heading">
      ${slide.eyebrow ? `<p class="viewer-eyebrow">${escapeHTML(slide.eyebrow)}</p>` : ""}
      ${slide.title ? `<h${isCover ? "1" : "2"} class="viewer-title">${escapeHTML(slide.title)}</h${isCover ? "1" : "2"}>` : ""}
      ${slide.lead ? `<p class="viewer-lead">${escapeHTML(slide.lead)}</p>` : ""}
    </header>`;

  const renderFigure = (figure) => {
    if (!figure || !figure.src) return "";
    return `<figure class="viewer-figure"><img src="${escapeHTML(safeHref(figure.src))}" alt="${escapeHTML(figure.alt || "")}">${figure.caption ? `<figcaption>${escapeHTML(figure.caption)}</figcaption>` : ""}</figure>`;
  };

  const renderLayout = (slide) => {
    switch (slide.layout) {
      case "cover":
        return `${renderHeading(slide, true)}${Array.isArray(slide.meta) && slide.meta.length ? `<ul class="viewer-cover-meta">${slide.meta.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>` : ""}`;
      case "cards":
        return `${renderHeading(slide)}<div class="viewer-card-grid">${(slide.cards || []).map((card) => `<section class="viewer-card">${card.label ? `<p class="viewer-card-label">${escapeHTML(card.label)}</p>` : ""}<h3 class="viewer-card-title">${escapeHTML(card.title || "")}</h3>${card.body ? `<p class="viewer-card-body">${escapeHTML(card.body)}</p>` : ""}</section>`).join("")}</div>`;
      case "bullets":
        return `${renderHeading(slide)}<ul class="viewer-bullet-list">${(slide.bullets || []).map((bullet) => `<li>${inlineBold(bullet)}</li>`).join("")}</ul>`;
      case "code":
        return `${renderHeading(slide)}<section class="viewer-code-block" aria-label="${escapeHTML(slide.code?.file || "코드 예시")}"><header class="viewer-code-header"><span class="viewer-code-file">${escapeHTML(slide.code?.file || "example.txt")}</span></header><pre><code>${escapeHTML(slide.code?.text || "")}</code></pre></section>`;
      case "statement":
        return `${renderHeading(slide)}<blockquote class="viewer-statement"><p>${escapeHTML(slide.statement || "")}</p></blockquote>`;
      case "table": {
        const table = slide.table || {};
        return `${renderHeading(slide)}<div class="viewer-table-wrap" tabindex="0" aria-label="표: ${escapeHTML(slide.title || "")}"><table class="viewer-table"><thead><tr>${(table.head || []).map((cell) => `<th scope="col">${escapeHTML(cell)}</th>`).join("")}</tr></thead><tbody>${(table.rows || []).map((row) => `<tr>${row.map((cell) => `<td>${escapeHTML(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      }
      case "figure":
        return `${renderHeading(slide)}${renderFigure(slide.figure)}`;
      case "split":
        return `${renderHeading(slide)}<div class="viewer-split">${renderFigure(slide.media)}<ul class="viewer-bullet-list">${(slide.bullets || []).map((bullet) => `<li>${inlineBold(bullet)}</li>`).join("")}</ul></div>`;
      default:
        return `${renderHeading(slide)}<p class="viewer-lead">이 장표의 layout 값을 확인해 주세요.</p>`;
    }
  };

  const renderSlide = (slide, { documentSlide = false, entering = false } = {}) => `
    <article id="slide-${escapeHTML(slide.id)}" class="viewer-slide layout-${escapeHTML(slide.layout || "bullets")}${documentSlide ? " viewer-document-slide" : ""}${entering ? " is-entering" : ""}" data-slide-id="${escapeHTML(slide.id)}">
      ${renderLayout(slide)}
      ${renderLinkAndCitations(slide)}
    </article>`;

  const makeSidebarNav = () => deck.groups.map((group) => {
    const sectionHtml = (group.sections || []).map((section) => {
      const sectionRecord = sections.find((candidate) => candidate.group === group && candidate.id === section.id);
      const start = sectionRecord ? sectionRecord.start : 0;
      return `<button class="viewer-section-button" type="button" data-section-start="${start}" aria-label="${escapeHTML(section.title || "섹션")} 섹션으로 이동"><span class="viewer-section-title">${escapeHTML(section.title || "제목 없음")}</span>${section.subtitle ? `<span class="viewer-section-subtitle">${escapeHTML(section.subtitle)}</span>` : ""}</button>`;
    }).join("");
    return `<section class="viewer-nav-group"><span class="viewer-group-label">${escapeHTML(group.label || "강의")}</span><div class="viewer-section-list">${sectionHtml}</div></section>`;
  }).join("");

  const makeTopbarLinks = () => [
    '<a class="viewer-topbar-pill viewer-global-pill" href="https://taehyeonglim.github.io/edtech/">홈</a>',
    '<a class="viewer-topbar-pill viewer-global-pill" href="https://taehyeonglim.github.io/edtech/chapters/">강의 목록</a>',
    ...(deck.textbook || []).map((item) =>
      `<a class="viewer-topbar-pill viewer-textbook-pill" href="${escapeHTML(safeHref(item.href))}">${escapeHTML(item.label || "텍스트 교재")}</a>`
    )
  ].join("");

  mount.innerHTML = `
    <div class="lecture-viewer${state.collapsed ? " is-sidebar-collapsed" : ""}" data-viewer-app>
      <aside class="viewer-sidebar" aria-label="강의 목차">
        <div class="viewer-brand"><a class="viewer-brand-link" href="${escapeHTML(safeHref(deck.hub || "#"))}" aria-label="과목 홈으로 이동"><p class="viewer-brand-eyebrow">${escapeHTML(deck.eyebrow || "")}</p><p class="viewer-brand-title">${escapeHTML(deck.title || "")}</p></a></div>
        <button class="viewer-sidebar-toggle" type="button" aria-label="사이드바 접기" aria-expanded="true">${icon.collapse}</button>
        <nav class="viewer-sidebar-nav" aria-label="섹션 목록">${makeSidebarNav()}</nav>
        <div class="viewer-sidebar-footer"><div class="viewer-progress-track" aria-hidden="true"><div class="viewer-progress-value"></div></div><span class="viewer-progress-text">1 / ${slides.length} 장표</span></div>
      </aside>
      <div class="viewer-drawer-scrim" aria-hidden="true"></div>
      <section class="viewer-stage" aria-label="강의 뷰어">
        <header class="viewer-topbar">
          <div class="viewer-breadcrumb-wrap"><button class="viewer-sidebar-open" type="button" aria-label="목차 열기" aria-expanded="false">${icon.menu}</button><div class="viewer-breadcrumb" aria-label="현재 위치"></div></div>
          <nav class="viewer-topbar-links" aria-label="과목 자료 이동">${makeTopbarLinks()}</nav>
        </header>
        <main class="viewer-main" tabindex="-1"><div class="viewer-slide-host"></div></main>
        <footer class="viewer-stage-footer" aria-label="장표 위치"></footer>
      </section>
      <nav class="viewer-dock" aria-label="강의 제어">
        <button type="button" data-action="previous" aria-label="이전 장표">${icon.previous}</button>
        <button type="button" data-action="grid" aria-label="전체 장표 보기 (G)">${icon.grid}</button>
        <button type="button" data-action="document" aria-label="문서 모드 전환 (M)" aria-pressed="false">${icon.document}</button>
        <button type="button" data-action="fullscreen" aria-label="전체화면 전환 (F)">${icon.fullscreen}</button>
        <button type="button" data-action="next" aria-label="다음 장표">${icon.next}</button>
      </nav>
      <div class="viewer-grid-overlay" role="dialog" aria-modal="true" aria-label="전체 장표 보기" aria-hidden="true">
        <div class="viewer-grid-inner"><header class="viewer-grid-header"><h2 class="viewer-grid-heading">전체 장표</h2><button class="viewer-grid-close" type="button" aria-label="전체 장표 보기 닫기">${icon.close}</button></header><div class="viewer-grid"></div></div>
      </div>
      <div class="viewer-live-region" aria-live="polite" aria-atomic="true"></div>
    </div>`;

  const app = mount.querySelector("[data-viewer-app]");
  const sidebar = app.querySelector(".viewer-sidebar");
  const sidebarToggle = app.querySelector(".viewer-sidebar-toggle");
  const sidebarOpen = app.querySelector(".viewer-sidebar-open");
  const scrim = app.querySelector(".viewer-drawer-scrim");
  const breadcrumb = app.querySelector(".viewer-breadcrumb");
  const host = app.querySelector(".viewer-slide-host");
  const main = app.querySelector(".viewer-main");
  const stageFooter = app.querySelector(".viewer-stage-footer");
  const progress = app.querySelector(".viewer-progress-value");
  const progressText = app.querySelector(".viewer-progress-text");
  const gridOverlay = app.querySelector(".viewer-grid-overlay");
  const grid = app.querySelector(".viewer-grid");
  const gridClose = app.querySelector(".viewer-grid-close");
  const liveRegion = app.querySelector(".viewer-live-region");
  const dock = app.querySelector(".viewer-dock");

  const isMobile = () => window.matchMedia("(max-width: 820px)").matches;
  const updateHash = (id) => {
    const hash = `#${encodeURIComponent(id)}`;
    if (window.location.hash !== hash) history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash}`);
  };

  const updateFrame = () => {
    const slide = slides[state.current];
    const section = slide.section;
    const position = `${state.current + 1} / ${slides.length}`;
    const pagePosition = `${String(state.current + 1).padStart(2, "0")} / ${String(slides.length).padStart(2, "0")}`;
    breadcrumb.innerHTML = `<span>${escapeHTML(slide.group.label || "강의")}</span><span class="viewer-breadcrumb-separator" aria-hidden="true">/</span><strong>${escapeHTML(section.title || "섹션")}</strong>`;
    stageFooter.textContent = pagePosition;
    progress.style.width = `${((state.current + 1) / slides.length) * 100}%`;
    progressText.textContent = `${position} 장표`;
    app.querySelectorAll(".viewer-section-button").forEach((button) => {
      button.classList.toggle("is-active", Number(button.dataset.sectionStart) === section.start);
      button.setAttribute("aria-current", Number(button.dataset.sectionStart) === section.start ? "true" : "false");
    });
    dock.querySelector('[data-action="previous"]').disabled = state.current === 0;
    dock.querySelector('[data-action="next"]').disabled = state.current === slides.length - 1;
    dock.querySelector('[data-action="document"]').setAttribute("aria-pressed", String(state.documentMode));
    liveRegion.textContent = `${position} 장표, ${slide.title || "제목 없음"}`;
  };

  const renderGrid = () => {
    grid.innerHTML = slides.map((slide, index) => `
      <button class="viewer-grid-card${index === state.current ? " is-current" : ""}" type="button" data-grid-index="${index}" aria-label="${index + 1}번 장표: ${escapeHTML(slide.title || "제목 없음")}">
        <span class="viewer-grid-index">${String(index + 1).padStart(2, "0")}</span>
        ${slide.eyebrow ? `<span class="viewer-eyebrow">${escapeHTML(slide.eyebrow)}</span>` : ""}
        <span class="viewer-grid-card-title">${escapeHTML(slide.title || "제목 없음")}</span>
      </button>`).join("");
  };

  const updateDocumentActive = (scrollToCurrent = false) => {
    host.querySelectorAll(".viewer-document-slide").forEach((element) => {
      element.setAttribute("aria-current", element.dataset.slideId === slides[state.current].id ? "true" : "false");
    });
    if (scrollToCurrent) {
      const current = host.querySelector(`[data-slide-id="${CSS.escape(slides[state.current].id)}"]`);
      current?.scrollIntoView({ block: "start", behavior: "auto" });
    }
  };

  const renderDocument = () => {
    host.classList.add("is-document");
    host.innerHTML = deck.groups.map((group) => `
      <section class="viewer-document-group">
        <p class="viewer-document-group-label">${escapeHTML(group.label || "강의")}</p>
        ${(group.sections || []).map((section) => `<section class="viewer-document-section"><h2 class="viewer-document-section-heading">${escapeHTML(section.title || "섹션")} ${section.subtitle ? `<small>${escapeHTML(section.subtitle)}</small>` : ""}</h2>${(section.slides || []).map((slide) => {
          const slideRecord = slides.find((candidate) => candidate.id === slide.id);
          return slideRecord ? renderSlide(slideRecord, { documentSlide: true }) : "";
        }).join("")}</section>`).join("")}
      </section>`).join("");
    updateDocumentActive(false);
  };

  const renderSingleSlide = () => {
    host.classList.remove("is-document");
    host.innerHTML = renderSlide(slides[state.current], { entering: true });
    main.scrollTop = 0;
  };

  const closeDrawer = () => {
    state.drawerOpen = false;
    app.classList.remove("is-drawer-open");
    sidebarOpen.setAttribute("aria-expanded", "false");
  };

  const openDrawer = () => {
    state.drawerOpen = true;
    app.classList.add("is-drawer-open");
    sidebarOpen.setAttribute("aria-expanded", "true");
    const active = sidebar.querySelector(".viewer-section-button.is-active");
    active?.focus();
  };

  const setSidebarCollapsed = (collapsed) => {
    state.collapsed = collapsed;
    app.classList.toggle("is-sidebar-collapsed", collapsed);
    storage.set("lecture-viewer:sidebar-collapsed", String(collapsed));
    sidebarToggle.setAttribute("aria-label", collapsed ? "사이드바 펼치기" : "사이드바 접기");
    sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
  };

  const setDocumentMode = (enabled, { scrollToCurrent = false } = {}) => {
    if (state.documentMode === enabled) return;
    state.documentMode = enabled;
    app.classList.toggle("is-document-mode", enabled);
    if (enabled) renderDocument();
    else renderSingleSlide();
    updateFrame();
    if (enabled && scrollToCurrent) requestAnimationFrame(() => updateDocumentActive(true));
  };

  const goTo = (index, { updateUrl = true, scrollDocument = true } = {}) => {
    const next = Math.max(0, Math.min(slides.length - 1, index));
    state.current = next;
    if (state.documentMode) updateDocumentActive(scrollDocument);
    else renderSingleSlide();
    updateFrame();
    renderGrid();
    if (updateUrl) updateHash(slides[next].id);
    if (isMobile()) closeDrawer();
  };

  const setGridOpen = (open) => {
    state.gridOpen = open;
    gridOverlay.classList.toggle("is-open", open);
    gridOverlay.setAttribute("aria-hidden", String(!open));
    if (open) {
      state.lastFocus = document.activeElement;
      renderGrid();
      gridClose.focus();
    } else if (state.lastFocus instanceof HTMLElement) {
      state.lastFocus.focus();
    }
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (app.requestFullscreen) await app.requestFullscreen();
    } catch (_) {
      liveRegion.textContent = "이 브라우저에서는 전체화면을 사용할 수 없습니다.";
    }
  };

  app.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "previous") goTo(state.current - 1);
    if (action === "next") goTo(state.current + 1);
    if (action === "grid") setGridOpen(!state.gridOpen);
    if (action === "document") setDocumentMode(!state.documentMode, { scrollToCurrent: true });
    if (action === "fullscreen") toggleFullscreen();

    const sectionButton = event.target.closest("[data-section-start]");
    if (sectionButton) goTo(Number(sectionButton.dataset.sectionStart));
    const gridButton = event.target.closest("[data-grid-index]");
    if (gridButton) { setGridOpen(false); goTo(Number(gridButton.dataset.gridIndex)); }
    if (event.target.closest(".viewer-grid-close")) setGridOpen(false);
    if (event.target.closest(".viewer-sidebar-toggle")) setSidebarCollapsed(!state.collapsed);
    if (event.target.closest(".viewer-sidebar-open")) openDrawer();
    if (event.target === scrim) closeDrawer();
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.matches("input, textarea, select, [contenteditable='true']")) return;
    if (event.key === "Escape") {
      if (state.gridOpen) { event.preventDefault(); setGridOpen(false); }
      else if (state.drawerOpen) { event.preventDefault(); closeDrawer(); }
      return;
    }
    if (event.key === "ArrowLeft") { event.preventDefault(); goTo(state.current - 1); }
    if (event.key === "ArrowRight") { event.preventDefault(); goTo(state.current + 1); }
    if (event.key.toLowerCase() === "g") { event.preventDefault(); setGridOpen(!state.gridOpen); }
    if (event.key.toLowerCase() === "m") { event.preventDefault(); setDocumentMode(!state.documentMode, { scrollToCurrent: true }); }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleFullscreen(); }
    if (event.key === "\\" && !isMobile()) { event.preventDefault(); setSidebarCollapsed(!state.collapsed); }
  });

  let touchStartX = null;
  main.addEventListener("touchstart", (event) => { touchStartX = event.changedTouches[0]?.clientX ?? null; }, { passive: true });
  main.addEventListener("touchend", (event) => {
    const endX = event.changedTouches[0]?.clientX;
    if (touchStartX === null || typeof endX !== "number") return;
    const distance = endX - touchStartX;
    touchStartX = null;
    if (Math.abs(distance) < 40 || state.documentMode || state.gridOpen) return;
    goTo(state.current + (distance < 0 ? 1 : -1));
  }, { passive: true });

  window.addEventListener("hashchange", () => {
    const hashIndex = indexFromHash();
    if (hashIndex !== -1 && hashIndex !== state.current) goTo(hashIndex, { updateUrl: false });
  });

  window.addEventListener("beforeprint", () => {
    state.beforePrintDocumentMode = state.documentMode;
    if (!state.documentMode) setDocumentMode(true);
  });
  window.addEventListener("afterprint", () => {
    if (state.beforePrintDocumentMode === false) setDocumentMode(false);
    state.beforePrintDocumentMode = null;
  });

  const initialIndex = indexFromHash();
  state.current = initialIndex === -1 ? 0 : initialIndex;
  renderSingleSlide();
  updateFrame();
  renderGrid();
  updateHash(slides[state.current].id);
})();
