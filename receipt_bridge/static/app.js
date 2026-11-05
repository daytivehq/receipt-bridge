"use strict";
const $ = (s) => document.querySelector(s);
const names = {
  dashboard: "대시보드",
  jobs: "작업 내역",
  upload: "사진 업로드",
  logs: "로그 조회",
  settings: "서비스 설정",
};
const states = {
  received: "수신 완료",
  processing: "분석 중",
  waiting: "확인 대기",
  creating: "거래 저장 중",
  attaching: "사진 첨부 중",
  done: "저장 완료",
  failed: "분석 실패",
  create_failed: "저장 확인 필요",
  attach_failed: "첨부 실패",
  cancelled: "취소",
};
const paths = {
  dashboard: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6",
  jobs: "M6 3h12v18l-3-2-3 2-3-2-3 2z M9 7h6 M9 11h6 M9 15h4",
  logs: "M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h4",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
  check: "M5 12l4 4L19 6",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2",
  alert: "M12 3L2 21h20z M12 9v5 M12 17v1",
  eye: "M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  eyeOff:
    "M3 3l18 18 M10 5a12 12 0 0 1 12 7 16 16 0 0 1-4 5 M6 6a17 17 0 0 0-4 6s3 7 10 7a12 12 0 0 0 5-1 M10 10a3 3 0 0 0 4 4",
  calendar: "M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16 M8 14h3 M8 17h7",
  telegram: "M3 10l18-7-5 18-5-6-5-2z M11 15l5-7",
  ai: "M7 7h10v10H7z M10 1v6 M14 1v6 M10 17v6 M14 17v6 M1 10h6 M1 14h6 M17 10h6 M17 14h6",
  ledger: "M5 3h14v18H5z M9 3v18 M12 8h4 M12 12h4",
};
function el(tag, props = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined)
      n.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return n;
}
function icon(name) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  n.setAttribute("viewBox", "0 0 24 24");
  n.setAttribute("width", "18");
  n.setAttribute("height", "18");
  n.classList.add("ui-icon");
  n.setAttribute("fill", "none");
  n.setAttribute("stroke", "currentColor");
  n.setAttribute("stroke-width", "1.5");
  n.setAttribute("stroke-linecap", "round");
  n.setAttribute("stroke-linejoin", "round");
  n.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(n.namespaceURI, "path");
  p.setAttribute("d", paths[name] || paths.jobs);
  n.append(p);
  return n;
}
function secretControl(input, label, loadStored = null) {
  const button = el(
    "button",
    {
      type: "button",
      class: "secret-toggle",
      "aria-controls": input.id,
      "aria-label": label + " 보기",
      "aria-pressed": "false",
      title: label + " 보기",
    },
    icon("eye"),
  );
  button.addEventListener("click", async () => {
    if (input.type === "password") {
      if (!input.value && loadStored) {
        button.disabled = true;
        try {
          const result = await loadStored();
          if (!input.isConnected || !csrf) return;
          if (!input.value) {
            input.value = result.value;
            input.dataset.savedPreview = "true";
            input.readOnly = true;
          }
        } catch (error) {
          toast(error.message);
          return;
        } finally {
          button.disabled = false;
        }
      }
      input.type = "text";
    } else {
      input.type = "password";
      if (input.dataset.savedPreview) {
        input.value = "";
        input.readOnly = false;
        delete input.dataset.savedPreview;
      }
    }
    const visible = input.type === "text";
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute("aria-label", label + (visible ? " 숨기기" : " 보기"));
    button.title = button.getAttribute("aria-label");
    button.replaceChildren(icon(visible ? "eyeOff" : "eye"));
  });
  return el("div", { class: "secret-control" }, input, button);
}
function badge(state) {
  const type = ["failed", "create_failed", "attach_failed"].includes(state)
    ? "orange"
    : state === "done"
      ? ""
      : state === "waiting"
        ? "blue"
        : "gray";
  return el("span", { class: "badge " + type }, states[state] || state);
}
function date(value) {
  return value
    ? new Date(value * 1000).toLocaleString("ko-KR", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "아직 없음";
}
let logTimezone = "Asia/Seoul";
function logDate(value) {
  if (value === null || value === undefined) return "—";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: logTimezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value * 1000));
  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}`;
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("#toast").hidden = true), 5000);
}
let setupRequired = false;
let uploadAbort = null;
let detailId = null, detailRequest = 0, detailTimer = null;
let csrf = "",
  page = "dashboard",
  overview = null,
  dirty = false,
  jobPage = 1,
  logPage = 1,
  logKind = "service";
async function api(path, body) {
  const options =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            "X-Receipt-Bridge": "1",
          },
          body: JSON.stringify(body),
        };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path != "/api/login") showLogin();
    const error = Error(data.error || "요청에 실패했습니다");
    error.status = response.status;
    throw error;
  }
  return data;
}
function setupMode(required) {
  setupRequired = required;
  $("#login-heading").textContent = required
    ? "처음 오셨네요."
    : "영수증을 기록으로.";
  $("#login-description").textContent = required
    ? "관리 비밀번호를 만들어 서비스를 시작하세요. 12자 이상으로 입력해 주세요."
    : "서비스 현황과 설정을 한곳에서 관리하세요.";
  $("#login-form").hidden = required;
  $("#setup-form").hidden = !required;
  for (const input of $("#setup-form").querySelectorAll("input")) input.disabled = !required;
  $("#password").disabled = required;
}
function showLogin() {
  document.querySelectorAll(".secret-control").forEach((control) => {
    const input = control.querySelector("input");
    input.value = "";
    input.type = "password";
    input.readOnly = false;
    delete input.dataset.savedPreview;
    const button = control.querySelector("button");
    button.setAttribute("aria-pressed", "false");
    button.setAttribute(
      "aria-label",
      button.getAttribute("aria-label").replace(" 숨기기", " 보기"),
    );
    button.title = button.getAttribute("aria-label");
    button.replaceChildren(icon("eye"));
  });
  uploadAbort?.abort();
  uploadAbort = null;
  $("#content").replaceChildren();
  detailId = null;
  detailRequest++;
  clearTimeout(detailTimer);
  $("#detail").close();
  $("#detail-body").replaceChildren();
  $("#app").hidden = true;
  $("#login").hidden = false;
  csrf = "";
  fetch("/api/session")
    .then((r) => r.json())
    .then((session) => setupMode(Boolean(session.setup_required)))
    .catch(() => {});
}
function setStatus(status) {
  const pill = $("#top-status");
  pill.className =
    "badge " + (!status.ready ? "orange" : status.paused ? "gray" : "");
  pill.textContent = status.demo
    ? "테스트 모드"
    : status.revision !== status.applied_revision
      ? "설정 적용 대기"
      : !status.ready
        ? "설정 필요"
        : status.paused
          ? "처리 일시정지"
          : "서비스 실행 중";
}
function head(title, description, action) {
  return el(
    "div",
    { class: "page-head" },
    el(
      "div",
      {},
      el("span", { class: "eyebrow" }, "RECEIPT BRIDGE / OPERATIONS"),
      el("h1", {}, title),
      el("p", {}, description),
    ),
    action || null,
  );
}
function card(title, body, extra) {
  return el(
    "section",
    { class: "card" },
    el("div", { class: "card-head" }, el("h2", {}, title), extra || null),
    body,
  );
}
function empty(title, description) {
  return el("div", { class: "empty" }, el("strong", {}, title), description);
}
function notice(status, detailed = true) {
  if (status.demo)
    return el(
      "div",
      { class: "notice" },
      "테스트 데이터로 보는 운영 화면입니다. Telegram·AI·가계부에 연결하지 않습니다.",
    );
  if (!status.ready && !detailed)
    return el(
      "div",
      { class: "notice warn" },
      "영수증 처리를 위한 설정이 필요합니다. ",
      el(
        "button",
        {
          type: "button",
          class: "link-button",
          onclick: () => navigate("settings"),
        },
        "서비스 설정에서 연결하기",
      ),
    );
  if (!status.ready)
    return el(
      "div",
      { class: "notice warn" },
      el("strong", {}, "영수증 처리를 시작하려면 다음 설정이 필요합니다."),
      el(
        "ul",
        {},
        ...(status.missing || ["서비스 설정의 필수 입력을 확인하세요."]).map(
          (item) => el("li", {}, item),
        ),
      ),
    );
  return null;
}
function jobTable(items) {
  if (!items.length)
    return empty(
      "아직 접수한 영수증이 없어요.",
      "텔레그램에 사진을 보내면 이곳에서 처리 흐름을 볼 수 있습니다.",
    );
  const table = el(
    "table",
    {},
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["영수증", "접수 시간", "결제 금액", "처리 상태", ""].map(
          (text, i) =>
            el(
              "th",
              { class: i === 1 ? "mobile-hide" : i === 2 ? "amount" : "" },
              text,
            ),
        ),
      ),
    ),
  );
  const body = el("tbody");
  for (const job of items) {
    const ex = job.extraction || {};
    const row = el(
      "tr",
      {
        "data-id": job.id,
        tabindex: "0",
        onclick: () => showDetail(job.id),
        onkeydown: (e) => {
          if (e.key === "Enter") showDetail(job.id);
        },
      },
      el(
        "td",
        {},
        el(
          "div",
          { class: "row-title" },
          el("span", { class: "receipt-icon" }, icon("jobs")),
          el(
            "div",
            {},
            ex.merchant || "영수증 분석 대기",
            el("small", { class: "mono" }, job.id),
          ),
        ),
      ),
      el("td", { class: "muted mobile-hide" }, date(job.created_at)),
      el(
        "td",
        { class: "amount" },
        ex.amount ? `${ex.amount} ${ex.currency || ""}` : "—",
      ),
      el("td", {}, badge(job.state)),
      el("td", { class: "muted" }, "›"),
    );
    body.append(row);
  }
  table.append(body);
  return el("div", { class: "table-wrap" }, table);
}
function metric(label, value, note, type) {
  return el(
    "div",
    { class: "stat " + (type === "alert" ? "error" : "") },
    el(
      "div",
      { class: "stat-top" },
      label,
      el("span", { class: "stat-icon" }, icon(type)),
    ),
    el("div", { class: "stat-number" }, value, el("small", {}, "건")),
    el("div", { class: "stat-foot" }, note),
  );
}
async function dashboard() {
  overview = await api("/api/overview");
  if (page !== "dashboard") return;
  const { status, summary, settings, recent } = overview;
  setStatus(status);
  const c = summary.counts;
  const fail =
    (c.failed || 0) + (c.create_failed || 0) + (c.attach_failed || 0);
  const pending =
    (c.received || 0) +
    (c.processing || 0) +
    (c.creating || 0) +
    (c.attaching || 0);
  const control = el(
    "button",
    {
      class: "button",
      onclick: async () => {
        try {
          await api("/api/control", { paused: !status.paused });
          toast(
            status.paused
              ? "영수증 처리를 재개했습니다."
              : "진행 중인 작업 뒤에 처리를 멈춥니다.",
          );
          await dashboard();
        } catch (e) {
          toast(e.message);
        }
      },
    },
    icon("clock"),
    status.paused ? "처리 재개" : "처리 일시정지",
  );
  const content = $("#content");
  content.replaceChildren(
    head(
      "서비스의 오늘을 살펴보세요",
      "영수증이 잘 도착하고, 차곡차곡 기록되고 있는지 확인하세요.",
      control,
    ),
  );
  const n = notice(status, false);
  if (n) content.append(n);
  content.append(
    el(
      "section",
      { class: "hero" },
      el(
        "div",
        {},
        el(
          "h2",
          {},
          status.paused
            ? "잠시 쉬어가는 중이에요."
            : fail
              ? "확인이 필요한 영수증이 있어요."
              : "사진 한 장이, 하나의 기록이 됩니다.",
        ),
        el(
          "p",
          {},
          status.paused
            ? "새로 받은 메시지는 보관하고, 다음 영수증 처리는 기다립니다."
            : `전체 ${summary.total}건의 영수증 중 ${c.done || 0}건을 저장했어요. 확인 대기 ${c.waiting || 0}건은 작업 내역에서 확인·저장하세요.`,
        ),
      ),
      el(
        "div",
        { class: "hero-art" },
        el("span", { class: "paper-icon" }, icon("jobs")),
        "···",
        el("span", { class: "paper-icon" }, icon("ai")),
        "···",
        el("span", { class: "paper-icon" }, icon("ledger")),
      ),
    ),
    el(
      "div",
      { class: "stats" },
      metric(
        "오늘 접수",
        summary.today,
        `전체 누적 ${summary.total}건`,
        "jobs",
      ),
      metric("저장 완료", c.done || 0, "거래와 영수증 첨부 완료", "check"),
      metric("확인 대기", c.waiting || 0, `처리 중 ${pending}건`, "clock"),
      metric("확인할 오류", fail, "재시도·설정 확인 필요", "alert"),
    ),
  );
  const days = [];
  const zone = settings.timezone;
  const key = (value) =>
    new Date(value).toLocaleDateString("sv-SE", { timeZone: zone });
  for (let i = 6; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000);
    days.push({
      key: key(d),
      label:
        i === 0
          ? "오늘"
          : d.toLocaleDateString("ko-KR", {
              timeZone: zone,
              month: "numeric",
              day: "numeric",
            }),
      count: 0,
    });
  }
  for (const entry of summary.dates) {
    const d = days.find((x) => x.key === key(entry.created_at * 1000));
    if (d) d.count++;
  }
  const max = Math.max(1, ...days.map((x) => x.count));
  const chart = el("div", {
    class: "chart",
    role: "img",
    "aria-label": "최근 7일 영수증 접수 건수",
  });
  for (const d of days) {
    const bar = el("div", { class: "chart-bar" });
    bar.style.height = `${Math.max(3, (d.count / max) * 126)}px`;
    chart.append(
      el(
        "div",
        { class: "chart-col" },
        el("span", { class: "chart-value" }, String(d.count)),
        bar,
      ),
    );
  }
  const chartCard = card(
    "한 주의 접수 흐름",
    el(
      "div",
      { class: "card-body" },
      chart,
      el(
        "div",
        { class: "chart-labels" },
        ...days.map((d) => el("span", {}, d.label)),
      ),
    ),
    el("span", { class: "legend" }, el("i", { class: "dot" }), "최근 7일"),
  );
  const connection = (name, description, ready, type, label) =>
    el(
      "div",
      { class: "connection" },
      el("span", { class: "connection-icon" }, icon(type)),
      el(
        "div",
        { class: "connection-text" },
        el("strong", {}, name),
        el("small", {}, description),
      ),
      el(
        "span",
        { class: "badge " + (ready ? "" : "orange") },
        label || (ready ? "설정됨" : "설정 필요"),
      ),
    );
  const connections = card(
    "서비스 연결",
    el(
      "div",
      { class: "card-body" },
      connection(
        "Telegram",
        status.last_poll
          ? `최근 수신 확인 ${date(status.last_poll)}`
          : "Long polling · 공개 수신 주소 불필요",
        status.checks.telegram,
        "telegram",
        status.poll_error
          ? "연결 오류"
          : status.last_poll
            ? "수신 확인"
            : status.checks.telegram
              ? "설정됨"
              : "설정 필요",
      ),
      connection(
        "AI 분석",
        `${settings.ai_provider} · ${settings.ai_model || "모델 미설정"}`,
        status.checks.ai,
        "ai",
      ),
      connection(
        "Duet Ledger",
        status.checks.ledger
          ? "계좌·분류·권한은 등록 시 검증"
          : "서버에 앱 비밀번호를 설정하세요",
        status.checks.ledger,
        "ledger",
      ),
    ),
    el(
      "button",
      { class: "link-button", onclick: () => navigate("settings") },
      "연결 설정 ↗",
    ),
  );
  content.append(
    el("div", { class: "grid-two" }, chartCard, connections),
    card(
      "최근 작업",
      jobTable(recent.items.slice(0, 5)),
      el(
        "button",
        { class: "link-button", onclick: () => navigate("jobs") },
        "전체 내역 보기 →",
      ),
    ),
    el(
      "div",
      { class: "save-bar" },
      el(
        "small",
        {},
        `메시지 수신 대기 ${summary.inbox}건 · 결과 안내 대기 ${summary.outbox}건`,
      ),
      el("small", {}, "10초마다 자동으로 새로고침"),
    ),
  );
}
function pagination(result, change) {
  return el(
    "div",
    { class: "pagination" },
    `${result.total}건 · ${result.page} / ${Math.max(1, Math.ceil(result.total / result.page_size))}페이지`,
    el(
      "div",
      {},
      el(
        "button",
        {
          class: "button",
          disabled: result.page === 1 ? "" : null,
          onclick: () => change(result.page - 1),
        },
        "이전",
      ),
      el(
        "button",
        {
          class: "button",
          disabled: result.page * result.page_size >= result.total ? "" : null,
          onclick: () => change(result.page + 1),
        },
        "다음",
      ),
    ),
  );
}
function uploadKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}
async function upload() {
  const content = $("#content");
  content.replaceChildren(head("사진 업로드", "영수증을 분석하고 이 화면에서 확인·수정·저장하세요."));
  const feedback = el("p", { id: "upload-feedback", role: "status" });
  const account = el("select", { id: "upload-account", required: "" });
  const files = el("input", { id: "upload-files", type: "file", accept: "image/jpeg,image/png,image/webp", multiple: "", required: "" });
  const caption = el("textarea", { id: "upload-caption", maxlength: "4096", placeholder: "예: 식비로 분류해줘" });
  const list = el("div", { id: "upload-results", class: "upload-results" });
  const button = el("button", { type: "submit", class: "primary", disabled: "" }, "분석 시작");
  const form = el("form", { id: "upload-form", class: "upload-form" },
    el("div", { class: "field" }, el("label", { for: account.id }, "저장 계좌"), account),
    el("div", { class: "field" }, el("label", { for: files.id }, "영수증 사진 · 여러 장 선택 가능"), files),
    el("div", { class: "field" }, el("label", { for: caption.id }, "사진 설명 (선택)"), caption,
      el("small", {}, "여러 장을 선택하면 같은 설명을 각 사진에 적용합니다.")),
    el("p", {}, "JPG·PNG·WebP를 최대 20장까지 업로드합니다. 분석 후 확인·저장을 눌러야 가계부에 등록됩니다."),
    feedback, button, list,
  );
  content.append(card("영수증 선택", form));
  let entries = [];
  let ready = false;
  let limit = 20;
  try {
    const [data, config] = await Promise.all([api("/api/accounts"), api("/api/settings")]);
    if (page !== "upload") return;
    setStatus(data.status);
    limit = config.settings.max_download_mb;
    account.append(...data.accounts.map((item) => el("option", { value: item.id }, `${item.name} · ${item.currency}`)));
    ready = data.status.web_ready ?? data.status.ready;
    button.disabled = !ready || !data.accounts.length;
    feedback.textContent = !data.accounts.length ? "저장 가능한 계좌가 없습니다. 가계부 앱 비밀번호의 계좌·권한을 확인하세요."
      : !ready ? "서비스 설정에서 가계부와 AI 설정을 완료하세요. Telegram 설정은 필요하지 않습니다."
      : data.status.paused ? "처리가 일시정지되어 있습니다. 접수 후 대시보드에서 처리를 재개하세요."
      : `사진 한 장당 ${limit}MB 이하입니다. 사진별로 차례로 분석합니다.`;
  } catch (error) { feedback.textContent = error.message; }
  files.addEventListener("change", () => { entries = []; list.replaceChildren(); button.textContent = "분석 시작"; button.disabled = !ready; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ready || uploadAbort) return;
    const selected = Array.from(files.files || []);
    if (!selected.length || selected.length > 20 || selected.some((file) => file.size > limit * 1024 * 1024)) {
      feedback.textContent = `사진을 1~20장 선택하세요. 한 장당 ${limit}MB 이하입니다.`;
      return;
    }
    const chosenAccount = account.value;
    const chosenCaption = caption.value.trim();
    if (!entries.length) entries = selected.map((file) => ({ file, key: uploadKey(), account: chosenAccount, caption: chosenCaption }));
    if (entries.some((entry) => !entry.id && (entry.account !== chosenAccount || entry.caption !== chosenCaption))) {
      feedback.textContent = "실패한 업로드는 같은 계좌·설명으로 재시도하세요. 내용을 바꾸려면 사진을 다시 선택하세요.";
      return;
    }
    const controller = new AbortController();
    uploadAbort = controller;
    dirty = true;
    button.disabled = true;
    for (const input of [files, account, caption]) input.disabled = true;
    try {
      for (const entry of entries) {
        if (entry.id) continue;
        const row = entry.row || el("div", { class: "upload-result" });
        entry.row = row;
        list.append(row);
        row.textContent = entry.file.name + " · 업로드 중…";
        try {
          const body = new FormData();
          body.append("account", entry.account);
          body.append("caption", entry.caption);
          body.append("file", entry.file);
          const response = await fetch("/api/uploads", { method: "POST", headers: { "X-CSRF-Token": csrf, "Idempotency-Key": entry.key }, body, signal: controller.signal });
          const data = await response.json();
          if (!response.ok) {
            if (response.status === 401) showLogin();
            throw Error(data.error || "사진 업로드에 실패했습니다.");
          }
          entry.id = data.id;
          row.replaceChildren(el("span", {}, entry.file.name + " · 분석 대기"), el("button", { type: "button", class: "button", onclick: () => showDetail(entry.id) }, "처리 결과 보기"));
        } catch (error) {
          row.textContent = entry.file.name + " · " + (controller.signal.aborted ? "업로드 중지" : error.message);
          if (controller.signal.aborted) break;
        }
      }
      if (page === "upload" && csrf) feedback.textContent = `${entries.filter((entry) => entry.id).length}/${entries.length}장 접수했습니다. 처리 결과 보기에서 분석 결과를 확인하세요.`;
    } finally {
      if (uploadAbort === controller) uploadAbort = null;
      if (page === "upload") dirty = false;
      for (const input of [files, account, caption]) input.disabled = false;
      button.disabled = entries.length > 0 && entries.every((entry) => entry.id);
      button.textContent = entries.some((entry) => !entry.id) ? "실패한 사진 다시 업로드" : "업로드 완료";
    }
  });
}

async function jobs(filters) {
  const content = $("#content");
  if (!filters) {
    content.replaceChildren(
      head(
        "영수증 작업 내역",
        "접수부터 저장까지, 영수증 한 장의 처리 과정을 확인하세요.",
      ),
    );
    const search = el("input", {
      id: "job-search",
      placeholder: "상호명 또는 작업 ID 검색",
      "aria-label": "작업 검색",
    });
    const select = el(
      "select",
      { id: "job-state", "aria-label": "작업 상태" },
      el("option", { value: "" }, "모든 상태"),
      ...Object.entries(states).map(([key, label]) =>
        el("option", { value: key }, label),
      ),
    );
    content.append(
      el(
        "form",
        {
          class: "filters",
          onsubmit: (e) => {
            e.preventDefault();
            jobPage = 1;
            loadJobs();
          },
        },
        search,
        select,
        el("button", { class: "button", type: "submit" }, "조회"),
      ),
      el("div", { id: "job-results" }),
    );
    select.addEventListener("change", () => {
      jobPage = 1;
      loadJobs();
    });
  }
  await loadJobs();
}
async function loadJobs() {
  const result = await api(
    `/api/jobs?page=${jobPage}&state=${encodeURIComponent($("#job-state").value)}&search=${encodeURIComponent($("#job-search").value)}`,
  );
  $("#job-results")?.replaceChildren(
    el(
      "div",
      { class: "card" },
      jobTable(result.items),
      pagination(result, (p) => {
        jobPage = p;
        loadJobs().catch((e) => toast(e.message));
      }),
    ),
  );
}
function logTimeInput(boundary, label) {
  return el("input", {
    id: "log-" + boundary,
    type: "text",
    placeholder: "2026-11-03 00:11",
    pattern: "[0-9]{4}-[0-9]{2}-[0-9]{2}[ T]([01][0-9]|2[0-3]):[0-5][0-9]",
    title: "YYYY-MM-DD HH:mm · 24시간 형식 (예: 2026-11-03 23:10)",
    "aria-label": "로그 " + label + " 일시",
  });
}
function logTimeControl(input, label) {
  const pickerId = input.id + "-picker";
  const dateInput = el("input", {
    type: "date",
    required: "",
    "aria-label": label + " 날짜",
  });
  const choice = (count, title) =>
    el(
      "select",
      { "aria-label": title },
      ...Array.from({ length: count }, (_, i) => {
        const value = String(i).padStart(2, "0");
        return el("option", { value }, value);
      }),
    );
  const hours = choice(24, label + " 시 (24시간)");
  const minutes = choice(60, label + " 분");
  const button = el(
    "button",
    {
      type: "button",
      class: "date-picker-button",
      "aria-label": label + " 선택",
      "aria-expanded": "false",
      "aria-controls": pickerId,
      title: label + " 선택",
    },
    icon("calendar"),
  );
  const close = () => {
    picker.hidden = true;
    dateInput.disabled = true;
    button.setAttribute("aria-expanded", "false");
  };
  const picker = el(
    "div",
    {
      id: pickerId,
      class: "date-picker",
      hidden: "",
      role: "group",
      "aria-label": label + " 선택",
      onkeydown: (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          close();
          button.focus();
        }
      },
    },
    el("label", {}, "날짜", dateInput),
    el(
      "div",
      { class: "time-choices" },
      el("label", {}, "시 (24시간)", hours),
      el("label", {}, "분", minutes),
    ),
    el(
      "div",
      { class: "filter-actions" },
      el(
        "button",
        {
          type: "button",
          class: "button",
          onclick: () => {
            if (!dateInput.reportValidity()) return;
            input.value = `${dateInput.value} ${hours.value}:${minutes.value}`;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            close();
            input.focus();
          },
        },
        "적용",
      ),
      el(
        "button",
        {
          type: "button",
          class: "button",
          onclick: () => {
            close();
            button.focus();
          },
        },
        "닫기",
      ),
    ),
  );
  dateInput.disabled = true;
  button.addEventListener("click", () => {
    if (!picker.hidden) {
      close();
      return;
    }
    // Use the service timezone; never convert the chosen wall time with browser timezone.
    const value = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$/.test(input.value)
      ? input.value.replace("T", " ")
      : logDate(Date.now() / 1000);
    dateInput.value = value.slice(0, 10);
    hours.value = value.slice(11, 13);
    minutes.value = value.slice(14, 16);
    dateInput.disabled = false;
    picker.hidden = false;
    button.setAttribute("aria-expanded", "true");
    dateInput.focus();
  });
  return el(
    "div",
    { class: "filter-field" },
    el("label", { for: input.id }, label + " (24시간)"),
    el("div", { class: "date-control" }, input, button, picker),
  );
}
async function logs() {
  const content = $("#content");
  content.replaceChildren(
    head("로그 조회", "서비스의 작은 변화와 작업별 처리 이력을 확인하세요."),
  );
  const search = el("input", {
    id: "log-search",
    placeholder: "내용·작업 ID·상태 코드 검색",
    "aria-label": "로그 내용 또는 작업 ID 검색",
  });
  const level = el(
    "select",
    { id: "log-level", "aria-label": "로그 수준" },
    ...Object.entries({
      "": "모든 수준",
      info: "안내",
      warning: "주의",
      error: "오류",
    }).map(([key, label]) => el("option", { value: key }, label)),
  );
  const start = logTimeInput("from", "시작");
  const end = logTimeInput("to", "종료");
  const tabs = el(
    "div",
    { class: "tabs" },
    ...Object.entries({ service: "서비스 로그", events: "작업 처리 이력" }).map(
      ([key, label]) =>
        el(
          "button",
          {
            class: key === logKind ? "active" : "",
            onclick: () => {
              logKind = key;
              logPage = 1;
              tabs
                .querySelectorAll("button")
                .forEach((b) =>
                  b.classList.toggle("active", b.textContent === label),
                );
              level.disabled = key === "events";
              loadLogs().catch((e) => toast(e.message));
            },
          },
          label,
        ),
    ),
  );
  level.disabled = logKind === "events";
  content.append(
    el(
      "form",
      {
        class: "filters log-filters",
        onsubmit: (e) => {
          e.preventDefault();
          logPage = 1;
          loadLogs().catch((e) => toast(e.message));
        },
      },
      el("label", { class: "filter-field" }, "내용 / 작업 ID", search),
      el("label", { class: "filter-field" }, "수준", level),
      logTimeControl(start, "시작 일시"),
      logTimeControl(end, "종료 일시"),
      el(
        "div",
        { class: "filter-actions" },
        el("button", { class: "button", type: "submit" }, "조회"),
        el(
          "button",
          {
            id: "log-reset",
            class: "button",
            type: "button",
            onclick: () => {
              search.value = "";
              level.value = "";
              start.value = "";
              end.value = "";
              logPage = 1;
              loadLogs().catch((e) => toast(e.message));
            },
          },
          "초기화",
        ),
      ),
      el(
        "small",
        { id: "log-timezone", class: "filter-note" },
        "서비스 시간대 기준 · 종료 시각은 해당 분까지 포함",
      ),
    ),
    el("section", { class: "card" }, tabs, el("div", { id: "log-results" })),
  );
  await loadLogs();
}
async function loadLogs() {
  const result = await api(
    `/api/logs?kind=${logKind}&level=${encodeURIComponent($("#log-level").value)}&search=${encodeURIComponent($("#log-search").value)}&from=${encodeURIComponent($("#log-from").value.trim().replace(" ", "T"))}&to=${encodeURIComponent($("#log-to").value.trim().replace(" ", "T"))}&page=${logPage}`,
  );
  logTimezone = result.timezone || overview?.settings?.timezone || "Asia/Seoul";
  if ($("#log-timezone"))
    $("#log-timezone").textContent =
      `기준 시간대: ${logTimezone} · 종료 시각은 해당 분까지 포함`;
  let body;
  if (!result.items.length)
    body = empty(
      "표시할 로그가 없습니다.",
      "조건을 바꾸거나 새로운 작업을 기다려 주세요.",
    );
  else {
    const table = el(
      "table",
      {},
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          ...["시간", "수준 / 상태", "내용", "작업 ID"].map((x) =>
            el("th", {}, x),
          ),
        ),
      ),
    );
    table.append(
      el(
        "tbody",
        {},
        ...result.items.map((row) =>
          el(
            "tr",
            {},
            el("td", { class: "muted log-time" }, logDate(row.at)),
            el(
              "td",
              {},
              row.state
                ? badge(row.state)
                : el(
                    "span",
                    {
                      class:
                        "badge " +
                        (row.level === "error"
                          ? "orange"
                          : row.level === "warning"
                            ? "blue"
                            : "gray"),
                    },
                    { info: "안내", warning: "주의", error: "오류" }[
                      row.level
                    ] || row.level,
                  ),
            ),
            el("td", {}, row.state ? "영수증 처리 상태 변경" : row.message),
            el(
              "td",
              {},
              row.job_id
                ? el(
                    "button",
                    {
                      class: "link-button mono",
                      onclick: () => showDetail(row.job_id),
                    },
                    row.job_id,
                  )
                : "—",
            ),
          ),
        ),
      ),
    );
    body = el("div", { class: "table-wrap" }, table);
  }
  $("#log-results")?.replaceChildren(
    body,
    pagination(result, (p) => {
      logPage = p;
      loadLogs().catch((e) => toast(e.message));
    }),
  );
}
async function showDetail(id, refresh = false) {
  if (!refresh) detailId = id;
  const request = ++detailRequest;
  try {
    const job = await api("/api/jobs/" + encodeURIComponent(id));
    if (request !== detailRequest || detailId !== id || (refresh && !$("#detail").open)) return;
    const body = $("#detail-body");
    body.replaceChildren(
      el(
        "div",
        { class: "notice" },
        "분석 결과를 확인하고 수정·저장할 수 있습니다. 가계부 저장은 확인·저장을 눌러 진행하세요.",
      ),
    );
    const ex = job.extraction || {};
    const facts = el("dl", { class: "detail-facts" });
    for (const [label, value] of [
      ["작업 ID", job.id],
      ["처리 상태", states[job.state] || job.state],
      ["입력 방식", job.input_kind === "text" ? "텍스트 지출" : "영수증 사진"],
      ["상호", ex.merchant || "—"],
      ["결제 금액", `${ex.amount || "—"} ${ex.currency || ""}`],
      ["결제 일시", `${ex.date || "—"} ${ex.time || ""}`],
      ["분류", ex.category || "—"],
      ["계좌", job.account],
      ["재시도", `${job.attempts}회`],
      ["거래 ID", job.posting_id || "—"],
    ])
      facts.append(el("dt", {}, label), el("dd", {}, value));
    if (job.error) body.append(el("div", { class: "notice warn" }, job.error));
    for (const warning of job.warnings || []) body.append(el("p", { class: "notice warn" }, warning));
    if ((job.duplicates || []).length) body.append(el("p", { class: "notice warn" }, "중복 후보: " + job.duplicates.map((item) => item.id).join(", ") + " · 기존 거래를 먼저 확인하세요."));
    const images = el("div");
    if (job.has_image || job.has_original) {
      const select = el(
        "select",
        { "aria-label": "사진 선택", class: "button" },
        ...(job.has_image
          ? [el("option", { value: "image" }, "보정 사진")]
          : []),
        ...(job.has_original
          ? [el("option", { value: "original" }, "원본 구도")]
          : []),
      );
      const img = el("img", {
        class: "detail-image",
        alt: "선택한 테스트 또는 수신 영수증",
        src: `/api/jobs/${encodeURIComponent(id)}/${select.value}`,
      });
      select.addEventListener(
        "change",
        () => (img.src = `/api/jobs/${encodeURIComponent(id)}/${select.value}`),
      );
      images.append(select, img);
    } else
      images.append(
        empty(
          job.input_kind === "text" ? "텍스트로 입력한 지출입니다." : "보관된 사진이 없습니다.",
          job.input_kind === "text" ? "사진 첨부 없이 거래만 저장합니다." : "다운로드가 시작되지 않았을 수 있습니다.",
        ),
      );
    if (job.input_text) body.append(
      el("h3", {}, job.input_kind === "text" ? "받은 텍스트" : "사진 설명"),
      el("p", { class: "input-source" }, job.input_text),
    );
    if (job.batch_size > 1) body.append(el("p", {}, `한 메시지의 ${job.batch_size}건 중 ${job.part + 1}번째 지출입니다. 각각 확인·저장합니다.`));
    body.append(
      el("div", { class: "detail-grid" }, images, facts),
      el("h3", {}, "처리 이력"),
      el(
        "ol",
        { class: "timeline" },
        ...job.events.map((event) =>
          el("li", {}, badge(event.state), el("time", {}, date(event.at))),
        ),
      ),
    );
    body.append(jobControls(job));
    if (!$("#detail").open) $("#detail").showModal();
    clearTimeout(detailTimer);
    if (["received", "processing", "creating", "attaching"].includes(job.state))
      detailTimer = setTimeout(() => showDetail(id, true), 2000);
  } catch (e) {
    if (detailId === id) toast(e.message);
  }
}
function jobControls(job) {
  const controls = el("div", { class: "job-controls" });
  const error = el("p", { role: "alert", class: "error-message" });
  async function control(action, values) {
    const data = await api(`/api/jobs/${encodeURIComponent(job.id)}/control`, { action, revision: job.revision ?? 0, ...(values ? { values } : {}) });
    if (detailId === data.id && $("#detail").open) await showDetail(data.id);
  }
  function action(label, name, primary = false) {
    const button = el("button", { type: "button", class: primary ? "primary" : "button", "data-job-action": name }, label);
    button.addEventListener("click", async () => {
      if (name === "confirm" && !confirm("이 내용으로 가계부에 거래를 등록할까요?")) return;
      button.disabled = true;
      try { await control(name); }
      catch (err) { error.textContent = err.message; button.disabled = false; }
    });
    controls.append(button);
  }
  if (job.state === "waiting") action("확인·저장", "confirm", true);
  const editable = ["waiting", "failed"].includes(job.state) && !job.posting_id;
  if (editable && job.extraction) {
    const edit = el("button", { type: "button", class: "button" }, "거래 정보 수정");
    edit.addEventListener("click", async () => {
      edit.disabled = true;
      try {
        const data = await api(`/api/jobs/${encodeURIComponent(job.id)}/categories`);
        const ex = job.extraction;
        const form = el("form", { class: "job-edit-form" });
        for (const [key, label, type] of [["merchant", "상호명", "text"], ["amount", "결제 금액", "text"], ["date", "결제 날짜", "date"], ["time", "결제 시간 (선택)", "time"], ["currency", "통화 코드", "text"]]) {
          const input = el("input", { id: "edit-" + key, name: key, type, value: ex[key] || "", step: key === "time" ? "60" : null, inputmode: key === "amount" ? "decimal" : null });
          form.append(el("div", { class: "field" }, el("label", { for: input.id }, label), input));
        }
        const category = el("select", { id: "edit-category", name: "category" }, el("option", { value: "" }, "분류를 선택하세요"), ...data.categories.map((item) => el("option", { value: item.code, selected: item.code === ex.category ? "" : null }, item.name)));
        form.append(el("div", { class: "field" }, el("label", { for: category.id }, "분류"), category), el("p", {}, "사진·설명이 다르면 사용할 값을 입력하세요. 수정 저장 후 확인·저장을 눌러 등록합니다."), el("button", { type: "submit", class: "primary" }, "이 값으로 수정"));
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          const values = Object.fromEntries(["merchant", "amount", "date", "time", "currency", "category"].map((key) => [key, form.elements.namedItem(key).value.trim() || null]));
          const submit = form.querySelector('button[type="submit"]');
          submit.disabled = true;
          try { await control("edit", values); }
          catch (err) { error.textContent = err.message; submit.disabled = false; }
        });
        controls.append(form);
        edit.remove();
      } catch (err) { error.textContent = err.message; edit.disabled = false; }
    });
    controls.append(edit);
  }
  if (["waiting", "failed"].includes(job.state) && !job.posting_id) action("취소", "cancel");
  if (["failed", "create_failed", "attach_failed"].includes(job.state)) action(job.state === "attach_failed" ? "사진 첨부 재시도" : "실패 단계 재시도", "retry");
  if (["received", "processing", "creating", "attaching"].includes(job.state)) {
    const refresh = el("button", { type: "button", class: "button", onclick: () => showDetail(job.id) }, "처리 상태 새로고침");
    controls.append(el("p", {}, "처리 중입니다. 잠시 후 상태를 새로고침하세요."), refresh);
  }
  controls.append(error);
  return controls;
}
const pagePaths = {
  dashboard: "/dashboard",
  jobs: "/jobs",
  upload: "/upload",
  logs: "/logs",
  settings: "/settings",
};
let historyIndex = history.state?.rbIndex ?? 0;
let restoringHistory = false;
function pageFromPath() {
  return (
    Object.keys(pagePaths).find(
      (key) => pagePaths[key] === location.pathname,
    ) || "dashboard"
  );
}
async function navigate(next, { mode = "push", index = historyIndex } = {}) {
  if (
    dirty &&
    next !== page &&
    !confirm("저장하지 않은 입력이 있습니다. 화면을 이동할까요?")
  )
    return false;
  if (page === "upload" && next !== page) uploadAbort?.abort();
  page = next in names ? next : "dashboard";
  dirty = false;
  if (mode === "pop") historyIndex = index;
  else if (mode === "replace" || location.pathname !== pagePaths[page]) {
    if (mode === "push") historyIndex++;
    history[mode === "replace" ? "replaceState" : "pushState"](
      { rbIndex: historyIndex },
      "",
      pagePaths[page],
    );
  }
  $("#breadcrumb").textContent = names[page];
  document.querySelectorAll("nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === page);
    b.setAttribute("aria-current", b.dataset.page === page ? "page" : "false");
  });
  try {
    await { dashboard, jobs, logs, settings, upload }[page]();
  } catch (e) {
    toast(e.message);
  }
  return true;
}
for (const button of document.querySelectorAll("nav button")) {
  button.prepend(icon(button.dataset.page));
  button.addEventListener("click", () => navigate(button.dataset.page));
}
$(".brand").addEventListener("click", (e) => {
  e.preventDefault();
  navigate("dashboard");
});
let loginPending = false;
async function submitLogin(event, setup) {
  event.preventDefault();
  if (loginPending || setup !== setupRequired) return;
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const password = $(setup ? "#setup-password" : "#password");
  const error = $(setup ? "#setup-error" : "#login-error");
  loginPending = true;
  button.disabled = true;
  try {
    if (setup && password.value !== $("#password-confirm").value)
      throw Error("비밀번호 확인이 일치하지 않습니다.");
    const data = await api(setup ? "/api/setup" : "/api/login", {
      password: password.value,
      ...(setup ? { confirmation: $("#password-confirm").value } : {}),
    });
    csrf = data.csrf;
    password.value = "";
    $("#password-confirm").value = "";
    error.textContent = "";
    $("#login").hidden = true;
    $("#app").hidden = false;
    await navigate(pageFromPath(), { mode: "replace" });
  } catch (err) {
    error.textContent = err.message;
    if (err.status === 409) {
      api("/api/session").then((session) => setupMode(Boolean(session.setup_required))).catch(() => {});
    }
  } finally {
    loginPending = false;
    button.disabled = false;
  }
}
$("#login-form").addEventListener("submit", (event) => submitLogin(event, false));
$("#setup-form").addEventListener("submit", (event) => submitLogin(event, true));
for (const [id, label] of [
  ["password", "관리 비밀번호"],
  ["setup-password", "새 관리 비밀번호"],
  ["password-confirm", "비밀번호 확인"],
]) {
  const input = $("#" + id);
  const parent = input.parentNode;
  const next = input.nextSibling;
  parent.insertBefore(secretControl(input, label), next);
}
const sidebarNote = $(".sidebar-note");
try {
  sidebarNote.hidden = localStorage.getItem("rb-hide-sidebar-note") === "1";
} catch {}
$("#dismiss-sidebar-note").addEventListener("click", () => {
  sidebarNote.hidden = true;
  try {
    localStorage.setItem("rb-hide-sidebar-note", "1");
  } catch {}
});
$("#logout").addEventListener("click", async () => {
  try {
    await api("/api/logout", {});
    dirty = false;
    showLogin();
  } catch (e) {
    toast(e.message);
  }
});
$("#refresh").addEventListener("click", () => {
  if (dirty) {
    toast("설정을 저장한 뒤 새로고침하세요.");
    return;
  }
  navigate(page);
});
$("#close-detail").addEventListener("click", () => $("#detail").close());
$("#detail").addEventListener("close", () => {
  detailId = null;
  detailRequest++;
  clearTimeout(detailTimer);
});
window.addEventListener("popstate", async (event) => {
  if (restoringHistory) {
    restoringHistory = false;
    return;
  }
  const previousIndex = historyIndex;
  const index = event.state?.rbIndex ?? 0;
  if (!$("#app").hidden) {
    const accepted = await navigate(pageFromPath(), { mode: "pop", index });
    if (!accepted && index !== previousIndex) {
      restoringHistory = true;
      history.go(previousIndex - index);
    }
  } else historyIndex = index;
});
window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
setInterval(() => {
  if (!$("#app").hidden && !$("#detail").open && page === "dashboard")
    dashboard().catch((e) => toast(e.message));
}, 10000);
(async () => {
  try {
    const session = await api("/api/session");
    if (session.authenticated) {
      csrf = session.csrf;
      setupMode(Boolean(session.setup_required));
      $("#app").hidden = false;
      await navigate(pageFromPath(), { mode: "replace" });
    } else showLogin();
  } catch (e) {
    showLogin();
    $("#login-error").textContent =
      "운영 서버에 연결하지 못했습니다. 잠시 후 새로고침하세요.";
  }
})();
