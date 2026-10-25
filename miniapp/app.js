const tg = window.Telegram?.WebApp;

function initTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    applyTheme(tg.themeParams);
  } catch (e) {
    console.warn("Telegram WebApp init:", e);
  }
}

initTelegram();

let catalog = null;
let faqData = null;
let query = "";

function setLoader(text) {
  const el = document.getElementById("loader") || document.getElementById("content");
  if (el) el.innerHTML = `<div class="loader">${escapeHtml(text)}</div>`;
}

function showError(message, canRetry) {
  const content = document.getElementById("content");
  const retryBtn = canRetry
    ? '<button type="button" class="retry-btn" id="retry-btn">Повторить загрузку</button>'
    : "";
  content.innerHTML =
    `<div class="empty error-box">${escapeHtml(message)}${retryBtn}</div>`;
  if (canRetry) {
    document.getElementById("retry-btn").onclick = () => boot(true);
  }
}

async function loadCatalog(attempt) {
  const maxAttempts = 3;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15000);
  try {
    setLoader(
      attempt > 1
        ? `Загрузка каталога… (попытка ${attempt}/${maxAttempts})`
        : "Загрузка каталога…"
    );
    const res = await fetch("/resources.json?_=" + Date.now(), {
      signal: ctrl.signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error("Сервер вернул " + res.status);
    const data = await res.json();
    if (!data.categories?.length) throw new Error("Каталог пуст");
    return data;
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error("Таймаут — сервер не ответил за 15 сек");
    }
    if (attempt < maxAttempts) {
      await new Promise((r) => setTimeout(r, 800 * attempt));
      return loadCatalog(attempt + 1);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function applyTheme(params) {
  if (!params || !params.bg_color) return;
  var bg = params.bg_color.toLowerCase();
  if (bg === "#ffffff" || bg === "#fff") return;
  var root = document.documentElement;
  if (params.secondary_bg_color) {
    root.style.setProperty("--card", params.secondary_bg_color);
  }
}

function typeLabel(type, item) {
  if (type === "video" && item && item.video_links && item.video_links.length) {
    var labels = item.video_links
      .map(function (l) {
        return l && l.label ? l.label : "";
      })
      .filter(Boolean);
    return labels.length ? labels.join(" / ") : "Видео";
  }
  if (type === "file" && item && item.file) {
    return { video: "Видео", pdf: "PDF", photo: "Фото", audio: "Аудио", file: "Файл" }[item.media] || "Файл";
  }
  if (type === "link") return "Ссылка";
  if (type === "info") return "Справка";
  return {
    link: "Ссылка",
    file: "Файл",
    video: "Видео",
    text: "Шаблон",
    info: "Справка",
  }[type] || "Материал";
}

function typeIcon(type, item) {
  if (item && item.media) {
    return { video: "🎬", pdf: "📄", photo: "🖼", audio: "🔊", file: "📎" }[item.media] || "📎";
  }
  return { link: "🔗", file: "📄", video: "🎬", text: "📝", info: "ℹ️" }[type] || "📎";
}

function fileUrl(name) {
  if (!name) return "";
  return "/files/" + encodeURIComponent(name);
}

function resolveUrl(item) {
  if (item.type === "file" && item.file) {
    return fileUrl(item.file);
  }
  const raw = item.url || "";
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  const path = raw.startsWith("/") ? raw : "/" + raw;
  return window.location.origin + path;
}

function isTelegramLink(url) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "").toLowerCase();
    return host === "t.me" || host === "telegram.me" || host === "telegram.dog";
  } catch (e) {
    return /^tg:/i.test(url);
  }
}

function isRealTelegramWebApp() {
  // В обычном браузере telegram-web-app.js тоже есть, но initData пустой
  return !!(tg && typeof tg.initData === "string" && tg.initData.length > 0);
}

function openUrl(url) {
  if (!url) return;
  if (isRealTelegramWebApp()) {
    try {
      if (tg.openTelegramLink && isTelegramLink(url)) {
        tg.openTelegramLink(url);
        return;
      }
      if (tg.openLink) {
        tg.openLink(url, { try_instant_view: false });
        return;
      }
    } catch (e) {
      console.warn("Telegram openUrl failed, fallback:", e);
    }
  }
  // Браузер / fallback: надёжнее через <a>, чем window.open (часто блокируют)
  var a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatRichText(text) {
  if (!text) return "";
  var escaped = escapeHtml(text);
  escaped = escaped.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" class="text-link" data-href="$1">$1</a>'
  );
  escaped = escaped.replace(/(@[a-zA-Z0-9_]{4,})/g, function (m) {
    var user = m.slice(1);
    var href = "https://t.me/" + user;
    return '<a href="' + href + '" class="text-link" data-href="' + href + '">' + m + "</a>";
  });
  return escaped;
}

function bindModalLinks(root) {
  if (!root) return;
  root.querySelectorAll(".text-link, .action-link-btn, .video-link-btn").forEach(function (btn) {
    btn.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      var href = btn.getAttribute("data-href") || btn.getAttribute("href");
      if (href) openUrl(href);
    };
  });
}

function closeModal() {
  var overlay = document.querySelector(".template-overlay");
  if (overlay) overlay.remove();
}

function openContentModal(item, opts) {
  opts = opts || {};
  closeModal();
  if (!item) return;

  var title = item.title || "";
  var bodyHtml = "";
  var actionsHtml = "";

  if (opts.bodyHtml) {
    bodyHtml = opts.bodyHtml;
  } else if (item.html) {
    bodyHtml =
      '<div class="template-body rich-text tg-rich" tabindex="0">' +
      item.html +
      "</div>";
  } else if (item.text) {
    bodyHtml = '<div class="template-body rich-text" tabindex="0">' + formatRichText(item.text) + "</div>";
  }

  if (opts.links && opts.links.length) {
    actionsHtml +=
      '<div class="video-links">' +
      opts.links
        .map(function (link) {
          return (
            '<button type="button" class="action-link-btn video-link-btn" data-href="' +
            escapeHtml(link.url) +
            '">▶ ' +
            escapeHtml(link.label || "Открыть ссылку") +
            "</button>"
          );
        })
        .join("") +
      "</div>";
  }

  if (opts.url) {
    actionsHtml +=
      '<div class="video-links">' +
      '<button type="button" class="action-link-btn" data-href="' +
      escapeHtml(opts.url) +
      '">🔗 Перейти по ссылке</button>' +
      '<p class="link-url-preview">' +
      escapeHtml(opts.url) +
      "</p></div>";
  }

  if (opts.fileUrl) {
    actionsHtml +=
      '<div class="video-links">' +
      '<button type="button" class="action-link-btn" data-href="' +
      escapeHtml(opts.fileUrl) +
      '">📂 Открыть файл</button></div>';
  }

  var footerHtml = "";
  if (opts.openUrl) {
    footerHtml =
      '<a class="copy-btn open-chat-btn" id="modal-open-btn" href="' +
      escapeHtml(opts.openUrl) +
      '" target="_blank" rel="noopener noreferrer">' +
      escapeHtml(opts.openLabel || "💬 Открыть чат") +
      "</a>";
  } else if (opts.copyText) {
    footerHtml =
      '<button type="button" class="copy-btn" id="modal-copy-btn">' +
      escapeHtml(opts.copyLabel || "📋 Скопировать") +
      "</button>" +
      '<p class="template-hint">Можно выделить текст вручную или нажать кнопку копирования</p>';
  }

  var overlay = document.createElement("div");
  overlay.className = "template-overlay";
  overlay.innerHTML =
    '<div class="template-modal" role="dialog" aria-modal="true">' +
    '<div class="template-header">' +
    '<h2 class="template-title">' +
    escapeHtml(title) +
    "</h2>" +
    '<button type="button" class="template-close" aria-label="Закрыть">✕</button>' +
    "</div>" +
    bodyHtml +
    actionsHtml +
    footerHtml +
    "</div>";

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) closeModal();
  });
  overlay.querySelector(".template-close").onclick = closeModal;
  bindModalLinks(overlay);

  var copyBtn = overlay.querySelector("#modal-copy-btn");
  if (copyBtn && opts.copyText) {
    copyBtn.onclick = function () {
      copyText(opts.copyText)
        .then(function () {
          hapticLight();
          flashToast("Скопировано");
        })
        .catch(function () {
          flashToast("Не удалось скопировать");
        });
    };
  }

  document.body.appendChild(overlay);
}

function openLinkModal(item) {
  openContentModal(item, { url: item.url || "" });
}

function openFileModal(item) {
  var url = resolveUrl(item);
  openContentModal(item, {
    bodyHtml: item.text
      ? '<div class="template-body rich-text">' + formatRichText(item.text) + "</div>"
      : "",
    fileUrl: url,
  });
}

function openVideoModal(item) {
  openContentModal(item, {
    bodyHtml: item.text
      ? '<div class="template-body rich-text">' + escapeHtml(item.text) + "</div>"
      : "",
    links: item.video_links || [],
  });
}

function extractChatUrl(item) {
  if (item && item.url) return item.url;
  var text = (item && item.text) || "";
  var m = text.match(/https?:\/\/t\.me\/[^\s]+/i);
  return m ? m[0] : "";
}

function openInfoModal(item) {
  var chatUrl = extractChatUrl(item);
  if (chatUrl) {
    openContentModal(item, {
      openUrl: chatUrl,
      openLabel: item.openLabel || "💬 Открыть чат",
    });
    return;
  }
  if (item.html || item.noCopy) {
    openContentModal(item, {});
    return;
  }
  openContentModal(item, {
    copyText: item.text,
    copyLabel: "📋 Скопировать текст",
  });
}

function openTemplate(item) {
  openContentModal(item, {
    copyText: item.text,
    copyLabel: "📋 Скопировать шаблон",
  });
}

function openItem(item) {
  if (item.type === "info") {
    openInfoModal(item);
    return;
  }
  if (item.type === "text") {
    openTemplate(item);
    return;
  }
  if (item.type === "video") {
    openVideoModal(item);
    return;
  }
  if (item.type === "link") {
    openUrl(item.url || resolveUrl(item));
    return;
  }
  if (item.type === "file" && item.file) {
    openUrl(resolveUrl(item));
    return;
  }
  var url = resolveUrl(item);
  if (url) openUrl(url);
}

function flashToast(message) {
  var existing = document.getElementById("toast");
  if (existing) existing.remove();
  var el = document.createElement("div");
  el.id = "toast";
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  requestAnimationFrame(function () {
    el.classList.add("show");
  });
  setTimeout(function () {
    el.classList.remove("show");
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 300);
  }, 2200);
}

function copyText(text) {
  return new Promise(function (resolve, reject) {
    if (!text) {
      reject(new Error("Пустой текст"));
      return;
    }
    if (tg && tg.writeTextToClipboard) {
      Promise.resolve(tg.writeTextToClipboard(text)).then(resolve).catch(reject);
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(resolve).catch(reject);
      return;
    }
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) resolve();
      else reject(new Error("copy failed"));
    } catch (e) {
      reject(e);
    }
  });
}

function hapticLight() {
  try {
    if (tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred) {
      tg.HapticFeedback.impactOccurred("light");
    }
  } catch (e) { /* ignore */ }
}

function copyTemplateQuick(item, event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  copyText(item.text)
    .then(function () {
      hapticLight();
      flashToast("Шаблон скопирован");
    })
    .catch(function () {
      openTemplate(item);
    });
}

async function loadFaq() {
  if (faqData) return faqData;
  const res = await fetch("/faq.json?_=" + Date.now(), {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error("FAQ: сервер вернул " + res.status);
  faqData = await res.json();
  return faqData;
}

function renderItemCard(item) {
  var icon = typeIcon(item.type, item);
  var isTemplate = item.type === "text";
  var isInfo = item.type === "info";
  var meta = item.note || typeLabel(item.type, item);
  var preview = "";
  if (isTemplate && item.text) {
    preview =
      '<div class="text-preview">' + escapeHtml(item.text.slice(0, 100)) + "…</div>";
  }
  var cardClass = "card" + (isTemplate ? " card-template" : "") + (isInfo ? " card-info" : "");
  var actionBtn = isTemplate
    ? '<button type="button" class="card-copy" title="Скопировать">📋</button>'
    : '<div class="card-arrow">›</div>';
  return (
    '<div class="' + cardClass + '" data-type="' + escapeHtml(item.type) + '">' +
    '<div class="card-icon">' + icon + "</div>" +
    '<div class="card-body">' +
    '<div class="card-title">' + escapeHtml(item.title) + "</div>" +
    '<div class="card-meta">' + escapeHtml(meta) + "</div>" +
    preview +
    "</div>" +
    actionBtn +
    "</div>"
  );
}

function bindCardHandlers(container, items) {
  container.querySelectorAll(".card").forEach(function (el, i) {
    var item = items[i];
    if (!item) return;
    if (item.type === "text") {
      el.onclick = function () {
        openTemplate(item);
      };
      var copyBtn = el.querySelector(".card-copy");
      if (copyBtn) {
        copyBtn.onclick = function (e) {
          e.preventDefault();
          e.stopPropagation();
          copyTemplateQuick(item, e);
        };
      }
      return;
    }
    el.onclick = function () {
      openItem(item);
    };
  });
}

function renderFaqBlock(items, hint) {
  if (!items.length) {
    return '<div class="empty">Ничего не найдено в FAQ</div>';
  }
  return (
    (hint || "") +
    items
      .map(function (item) {
        return (
          '<details class="faq-item">' +
          '<summary class="faq-q">' + escapeHtml(item.q) + "</summary>" +
          '<div class="faq-a">' + escapeHtml(item.a) + "</div>" +
          "</details>"
        );
      })
      .join("")
  );
}

async function renderCatalog() {
  var content = document.getElementById("content");
  if (!catalog || !catalog.categories) {
    content.innerHTML = '<div class="empty">Нет категорий</div>';
    return;
  }

  var sections = [];
  var allItemsFlat = [];

  catalog.categories.forEach(function (cat) {
    var items = (cat.items || []).filter(function (it) {
      return matchItem(it, query);
    });
    if (!items.length) return;

    var openAttr = query ? " open" : "";
    sections.push(
      '<details class="cat-section"' + openAttr + '>' +
      '<summary class="cat-summary">' +
      escapeHtml((cat.icon || "") + " " + cat.title) +
      (query ? " (" + items.length + ")" : "") +
      "</summary>" +
      '<div class="cat-items" data-cat="' + escapeHtml(cat.id) + '">' +
      items.map(renderItemCard).join("") +
      "</div></details>"
    );
    allItemsFlat = allItemsFlat.concat(items);
  });

  if (!faqData) {
    try {
      await loadFaq();
    } catch (e) {
      /* FAQ подгрузится при следующем рендере */
    }
  }

  if (faqData && faqData.items) {
    var faqItems = faqData.items.filter(function (it) {
      return matchFaqItem(it, query);
    });
    if (!query && faqItems.length > 50 && faqData.count > 50) {
      faqItems = faqItems.slice(0, 50);
    }
    if (faqItems.length || !query) {
      var faqHint = "";
      if (!query && faqData.count > faqItems.length) {
        faqHint =
          '<p class="faq-hint">Показаны первые ' +
          faqItems.length +
          " из " +
          faqData.count +
          ". Введите поиск для остальных.</p>";
      } else if (query) {
        faqHint = '<p class="faq-hint">Найдено: ' + faqItems.length + "</p>";
      }
      var openFaq = query && faqItems.length ? " open" : "";
      sections.push(
        '<details class="cat-section"' + openFaq + '>' +
        '<summary class="cat-summary">❓ FAQ' +
        (query && faqItems.length ? " (" + faqItems.length + ")" : "") +
        "</summary>" +
        '<div class="cat-items cat-faq">' +
        renderFaqBlock(faqItems, faqHint) +
        "</div></details>"
      );
    }
  }

  if (!sections.length) {
    content.innerHTML = '<div class="empty">Ничего не найдено</div>';
    return;
  }

  content.innerHTML = sections.join("");

  content.querySelectorAll(".cat-items[data-cat]").forEach(function (wrap) {
    var catId = wrap.getAttribute("data-cat");
    var cat = catalog.categories.find(function (c) {
      return c.id === catId;
    });
    if (!cat) return;
    var items = (cat.items || []).filter(function (it) {
      return matchItem(it, query);
    });
    bindCardHandlers(wrap, items);
  });
}

function renderItems() {
  renderCatalog();
}

function matchFaqItem(item, q) {
  if (!q) return true;
  var blob = (item.q + " " + item.a).toLowerCase();
  return blob.indexOf(q) !== -1;
}

function matchItem(item, q) {
  if (!q) return true;
  var blob = (item.title + " " + (item.note || "") + " " + (item.text || "")).toLowerCase();
  return blob.indexOf(q) !== -1;
}

document.getElementById("search").addEventListener("input", function (e) {
  query = e.target.value.trim().toLowerCase();
  renderItems();
});

async function boot(fromRetry) {
  if (fromRetry) setLoader("Повторная загрузка…");
  try {
    catalog = await loadCatalog(1);
    document.getElementById("app-title").textContent = catalog.title || "Материалы";
    document.getElementById("app-subtitle").textContent =
      catalog.subtitle || "Инструкции и ссылки";
    await renderCatalog();
  } catch (e) {
    var hint =
      "Проверьте интернет и обновите Telegram. " +
      "Если не помогло — откройте https://materials.emarbot.ru/ в браузере.";
    showError((e && e.message) || "Неизвестная ошибка", true);
    console.error("Mini App load error:", e, hint);
  }
}

boot(false);
