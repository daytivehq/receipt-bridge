"use strict";

const secretFields = [
  ["telegram_token", "Telegram 봇 토큰"],
  ["ledger_password", "가계부 앱 비밀번호"],
];

const AI_PROVIDERS = {
  ollama: {
    label: "Ollama · 로컬 분석",
    modelHint: "로컬에 설치한 이미지 분석 모델 이름",
    description: "Ollama가 실행 중이고 선택한 모델이 설치되어 있어야 합니다.",
  },
  codex: {
    label: "Codex CLI",
    modelHint: "사용 가능한 Codex 모델 이름",
    description:
      "전용 분석 서비스에서 실행합니다. 최초 한 번 로그인하고 외부 AI 전송 허용을 켜세요.",
  },
  claude: {
    label: "Claude Code CLI",
    modelHint: "사용 가능한 Claude 모델 이름",
    description:
      "아래에서 Claude API 키를 저장하세요. 외부 AI 전송 허용이 필요하며 API 요금이 발생할 수 있습니다.",
  },
  agy: {
    label: "Antigravity CLI · OCR 텍스트 분석",
    modelHint: "gemini-3.8-flash-low",
    description:
      "사진은 로컬 OCR로 읽고 텍스트만 전달합니다. 최초 한 번 Google 로그인과 외부 AI 전송 허용이 필요합니다.",
  },
};

const settingsSections = [
  {
    key: "ledger",
    title: "가계부 연결",
    description:
      "Duet Ledger의 저장 위치입니다. 가계부 사용자 ID는 입력하지 않습니다.",
    fields: [
      [
        "ledger_url",
        "가계부 API 주소",
        "text",
        "http://서버주소:포트/api/v1",
        true,
      ],
    ],
  },
  {
    key: "telegram",
    title: "메신저 연결 · Telegram",
    description:
      "허용된 사람과 대화방에서만 영수증을 받습니다. 개인 대화에서는 두 ID가 보통 같습니다.",
    fields: [
      [
        "allowed_users",
        "Telegram 허용 사용자 ID (사람 번호)",
        "ids",
        "숫자를 쉼표로 구분",
      ],
      [
        "allowed_chats",
        "Telegram 허용 채팅 ID (대화방 번호)",
        "ids",
        "그룹 번호는 음수도 가능합니다",
      ],
      [
        "user_accounts",
        "Telegram 사용자별 저장 계좌",
        "map",
        "텔레그램사용자ID = 가계부계좌ID",
        true,
      ],
      [
        "chat_accounts",
        "Telegram 대화방별 저장 계좌 (선택)",
        "map",
        "텔레그램채팅ID = 가계부계좌ID",
        true,
      ],
    ],
  },
  {
    key: "ai",
    title: "AI 분석",
    description: "선택한 AI에만 보정 사진과 분류 정보를 전달합니다.",
    fields: [
      ["ai_provider", "AI 제공자", "provider", ""],
      ["ai_model", "모델 이름", "text", "이미지 입력을 지원하는 모델"],
      [
        "ollama_url",
        "Ollama 주소",
        "text",
        "http://host.docker.internal:11434",
        true,
      ],
      [
        "ai_runner_url",
        "CLI 분석 서비스 주소",
        "text",
        "http://ai-runner:8090",
        true,
      ],
      ["ai_timeout", "분석 제한 시간 (초)", "number", "180"],
      ["ocr_languages", "로컬 OCR 언어", "text", "kor+eng"],
    ],
  },
  {
    key: "processing",
    title: "공통 처리와 재시도",
    description: "전송과 분석이 실패했을 때의 동작을 정합니다.",
    fields: [
      ["timezone", "서비스 시간대", "text", "Asia/Seoul"],
      ["max_download_mb", "사진 수신 한도 (MB)", "number", "20"],
      ["max_attempts", "최대 시도 횟수", "number", "5"],
      ["retry_seconds", "첫 재시도 대기 (초)", "number", "30"],
      [
        "max_amount_minor",
        "등록 최대 금액 (최소 통화 단위)",
        "number",
        "9000000000000",
      ],
    ],
  },
  {
    key: "auto_save",
    title: "자동 저장 조건",
    description: "기본은 텔레그램에서 확인한 뒤 저장합니다.",
    fields: [
      [
        "auto_max_amount_minor",
        "자동 저장 최대 금액 (최소 통화 단위)",
        "number",
        "50000",
      ],
      ["auto_max_age_days", "자동 저장 날짜 범위 (일)", "number", "7"],
    ],
  },
];
function settingsToggle(key, label, description, value) {
  const input = el("input", {
    type: "checkbox",
    name: key,
    id: "set-" + key,
    "aria-label": label,
    checked: value ? "" : null,
  });
  return el(
    "div",
    { class: "toggle-row" },
    el("div", {}, el("strong", {}, label), el("small", {}, description)),
    el("label", { class: "toggle" }, input, el("span")),
  );
}
function settingsField(spec, value) {
  const [key, label, type, placeholder, full] = spec;
  let input;
  if (type === "provider")
    input = el(
      "select",
      { name: key, id: "set-" + key },
      ...Object.entries(AI_PROVIDERS).map(([val, { label: title }]) =>
        el(
          "option",
          { value: val, selected: value === val ? "" : null },
          title,
        ),
      ),
    );
  else if (type === "map")
    input = el(
      "textarea",
      { name: key, id: "set-" + key, placeholder, spellcheck: "false" },
      Object.entries(value)
        .map(([id, account]) => `${id} = ${account}`)
        .join("\n"),
    );
  else
    input = el("input", {
      name: key,
      id: "set-" + key,
      type:
        type === "number" && !key.endsWith("_amount_minor") ? "number" : "text",
      value:
        type === "ids"
          ? value.join(", ")
          : key.endsWith("_amount_minor")
            ? Number(value).toLocaleString("en-US")
            : value,
      placeholder,
      step: type === "number" ? "1" : null,
      inputmode: key.endsWith("_amount_minor") ? "numeric" : null,
    });
  if (key.endsWith("_amount_minor")) {
    input.addEventListener("input", () => {
      const raw = input.value.replaceAll(",", "");
      if (!/^\d+$/.test(raw)) return;
      const before = input.value
        .slice(0, input.selectionStart)
        .replaceAll(",", "").length;
      const formatted = raw
        .replace(/^0+(?=\d)/, "")
        .replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      input.value = formatted;
      let digits = 0,
        cursor = 0;
      while (cursor < formatted.length && digits < before) {
        if (formatted[cursor] !== ",") digits++;
        cursor++;
      }
      input.setSelectionRange(cursor, cursor);
    });
  }
  return el(
    "div",
    { class: "field " + (full ? "full" : ""), "data-setting": key },
    el("label", { for: "set-" + key }, label),
    input,
    type === "map"
      ? el(
          "small",
          {},
          "한 줄에 하나씩 입력합니다. 사용자별 설정이 채팅별 설정보다 우선합니다.",
        )
      : null,
  );
}
function credentialField(key, label, saved) {
  const input = el("input", {
    id: "secret-" + key,
    name: key,
    type: "password",
    autocomplete: "new-password",
    value: "",
    placeholder: saved
      ? "저장됨 · 보기 버튼으로 확인하거나 새 값을 입력하세요"
      : "연결할 접속 키를 입력하세요",
  });
  return el(
    "div",
    { class: "field full" },
    el("label", { for: input.id }, label),
    secretControl(
      input,
      label,
      saved ? () => api("/api/settings/reveal-secret", { key }) : null,
    ),
    el(
      "small",
      {},
      saved
        ? "보기 버튼으로 저장된 값을 확인할 수 있습니다. 변경하려면 숨긴 뒤 새 값을 입력하세요. 비워 두면 기존 값을 유지합니다."
        : "입력한 값은 서버의 데이터 볼륨에 보관합니다.",
    ),
    el(
      "label",
      { class: "clear-secret" },
      el("input", { type: "checkbox", name: "remove_" + key }),
      " 저장된 값 지우기",
    ),
  );
}

function appendSettingsSections(form, values, savedSecrets) {
  const secretCards = Object.fromEntries(
    secretFields.map(([key, label]) => [
      key,
      credentialField(key, label, savedSecrets[key]),
    ]),
  );
  for (const { key, title, description, fields } of settingsSections) {
    const section = card(
      title,
      el(
        "div",
        { class: "fields" },
        ...fields.map((spec) => settingsField(spec, values[spec[0]])),
      ),
      el("small", {}, description),
    );
    section.classList.add("settings-section");
    if (key === "ledger")
      section.querySelector(".fields").append(secretCards.ledger_password);
    if (key === "telegram") {
      section.querySelector(".fields").prepend(secretCards.telegram_token);
      section.append(
        el(
          "p",
          { class: "section-help" },
          "저장 계좌에는 가계부 계좌의 고유 ID를 입력하세요. 사용자별 계좌가 대화방별 계좌보다 우선하며, 지정된 계좌에만 등록할 수 있습니다.",
        ),
      );
    }
    if (key === "ai") {
      section.append(
        settingsToggle(
          "allow_external_ai",
          "외부 AI 전송 허용",
          "Codex·Claude는 사진을, Antigravity는 로컬 OCR로 읽은 텍스트를 해당 AI 제공자에게 전달합니다.",
          values.allow_external_ai,
        ),
        aiSetupControls(form, values),
      );
    }
    if (key === "auto_save")
      section.append(
        settingsToggle(
          "auto_save",
          "검증을 통과한 영수증 자동 저장",
          "금액·날짜·독립 OCR·합계 대조를 모두 통과해야 합니다. 중복이나 경고가 있으면 확인을 기다립니다.",
          values.auto_save,
        ),
      );
    form.append(section);
    if (key === "telegram") {
      for (const name of ["Slack", "Discord"]) {
        const planned = card(
          "메신저 연결 · " + name,
          el(
            "p",
            { class: "section-help" },
            "연동 준비 중 · 현재는 연결할 수 없습니다.",
          ),
        );
        planned.classList.add("settings-section", "planned-connection");
        form.append(planned);
      }
      form.append(
        el(
          "p",
          { class: "section-help" },
          "현재는 Telegram만 지원합니다. Slack·Discord 지원 시 Telegram 없이 하나만 사용하거나, 여러 메신저를 함께 사용할 수 있도록 확장할 예정입니다.",
        ),
      );
    }
  }
}

function aiSetupControls(form, values) {
  const result = el("p", { id: "ai-check-result", role: "status" });
  const models = el("div", { id: "ai-model-options", class: "ai-model-options" });
  const check = el("button", { type: "button", id: "ai-check" }, "연결·설치 확인");
  const input = el("input", {
    id: "ai-api-key", type: "password", autocomplete: "new-password",
    placeholder: "Claude API 키 · 저장 후 입력칸을 비웁니다",
  });
  const saveKey = el("button", { type: "button", id: "ai-key-save" }, "API 키 저장");
  function requireSaved() {
    if (dirty || form.elements.namedItem("ai_provider").value !== values.ai_provider)
      throw Error("먼저 변경 사항 저장을 눌러 AI 설정을 저장하세요.");
  }
  check.addEventListener("click", async () => {
    try {
      requireSaved();
      check.disabled = true;
      result.textContent = "분석 서비스 연결을 확인하고 있습니다…";
      const data = await api("/api/ai/check", {});
      result.textContent = data.message;
      models.replaceChildren();
      for (const model of data.models || []) {
        const button = el("button", { type: "button" }, model);
        button.addEventListener("click", () => {
          form.elements.namedItem("ai_model").value = model;
          dirty = true;
          result.textContent = "모델을 선택했습니다. 변경 사항 저장을 눌러 적용하세요.";
        });
        models.append(button);
      }
    } catch (error) { result.textContent = error.message; }
    finally { check.disabled = false; }
  });
  saveKey.addEventListener("click", async () => {
    try {
      requireSaved();
      saveKey.disabled = true;
      await api("/api/ai/credentials", { key: input.value.trim() });
      input.value = "";
      input.type = "password";
      result.textContent = "API 키를 분석 서비스에 저장했습니다.";
    } catch (error) { result.textContent = error.message; }
    finally { saveKey.disabled = false; }
  });
  return el("div", { id: "ai-setup", class: "ai-setup" },
    el("p", {}, "CLI는 분석 이미지에 포함되어 있습니다. 제공자·모델을 바꿔도 다시 설치하지 않습니다. 통신용 토큰은 자동 관리합니다."),
    check, result, models,
    el("div", { id: "ai-claude-key", class: "field" },
      el("label", { for: "ai-api-key" }, "Claude API 키"),
      secretControl(input, "Claude API 키"), saveKey,
      el("small", {}, "분석 전용 저장 공간에 보관합니다. 기존 키는 입력하지 않으면 유지합니다.")),
    el("details", { id: "ai-login-guide" },
      el("summary", {}, "최초 계정 로그인 방법"),
      el("p", {}, "서버 터미널에서 다음 명령을 한 번 실행하고 표시되는 주소에서 로그인하세요. Antigravity는 브라우저의 인증 코드를 터미널에 입력합니다. 로그인 정보는 분석 볼륨에 유지됩니다."),
      el("pre", {}, el("code", { id: "ai-login-command" }))),
  );
}

function configureAIFields(form, values) {
  let previousProvider = values.ai_provider;
  const modelDrafts = { [previousProvider]: values.ai_model };
  function updateAIFields() {
    const provider = form.elements.namedItem("ai_provider").value;
    if (provider !== previousProvider) {
      modelDrafts[previousProvider] = form.elements.namedItem("ai_model").value;
      form.elements.namedItem("ai_model").value = modelDrafts[provider] || "";
      previousProvider = provider;
    }
    for (const [key, visible] of Object.entries({
      ollama_url: provider === "ollama",
      ai_runner_url: provider !== "ollama",
    }))
      form.querySelector(`[data-setting="${key}"]`).hidden = !visible;
    form.querySelector("#set-allow_external_ai").closest(".toggle-row").hidden =
      provider === "ollama";
    form.querySelector("#ai-setup").hidden = provider === "ollama";
    form.querySelector("#ai-claude-key").hidden = provider !== "claude";
    form.querySelector("#ai-login-guide").hidden = provider === "claude";
    form.querySelector("#ai-login-command").textContent = provider === "codex"
      ? "docker compose run --rm -e HOME=/ai-home -e CODEX_HOME=/ai-home/.codex --entrypoint codex ai-runner login --device-auth"
      : 'docker compose run --rm -e HOME=/ai-home -e SSH_CONNECTION="127.0.0.1 1 127.0.0.1 22" --entrypoint agy ai-runner';
    form.querySelector("#ai-check-result").textContent = "설정을 저장한 뒤 분석 서비스 연결을 확인하세요.";
    form.querySelector("#ai-model-options").replaceChildren();
    const { modelHint, description } = AI_PROVIDERS[provider];
    form.elements.namedItem("ai_model").placeholder = modelHint;
    providerHelp.textContent = description;
  }
  const providerHelp = el("p", {
    id: "ai-provider-help",
    class: "section-help",
  });
  form
    .querySelector("#set-ai_provider")
    .closest("section")
    .append(providerHelp);
  form.elements
    .namedItem("ai_provider")
    .addEventListener("change", updateAIFields);
  updateAIFields();
}

function parseSettingValue(key, type, raw) {
  if (type === "ids") {
    return raw
      ? raw
          .split(/[\s,]+/)
          .filter(Boolean)
          .map((id) => {
            if (!/^-?\d+$/.test(id) || !Number.isSafeInteger(Number(id)))
              throw Error("허용 ID는 정수로 입력하세요.");
            return Number(id);
          })
      : [];
  } else if (type === "map") {
    const mapping = {};
    for (const line of raw.split("\n").filter((x) => x.trim())) {
      const match = line.match(/^\s*(-?\d+)\s*=\s*(\S+)\s*$/);
      if (!match) throw Error("기본 계좌는 ID = 계좌ID 형식으로 입력하세요.");
      mapping[match[1]] = match[2];
    }
    return mapping;
  } else if (type === "number") {
    const number = key.endsWith("_amount_minor")
      ? raw.replaceAll(",", "")
      : raw;
    if (!/^\d+$/.test(number) || !Number.isSafeInteger(Number(number)))
      throw Error("숫자 설정은 정수로 입력하세요.");
    return Number(number);
  } else return raw;
}

function settingsPayload(form) {
  const payload = {};
  for (const { fields } of settingsSections)
    for (const [key, , type] of fields) {
      const raw = form.elements.namedItem(key).value.trim();
      payload[key] = parseSettingValue(key, type, raw);
    }
  payload.auto_save = form.elements.namedItem("auto_save").checked;
  payload.allow_external_ai =
    form.elements.namedItem("allow_external_ai").checked;
  payload.secrets = {};
  for (const [key] of secretFields) {
    const value = form.elements.namedItem(key).value.trim();
    if (form.elements.namedItem("remove_" + key).checked)
      payload.secrets[key] = null;
    else if (value && !form.elements.namedItem(key).dataset.savedPreview)
      payload.secrets[key] = value;
  }
  return payload;
}

function bindSettingsSave(form, values) {
  form.addEventListener("input", (event) => {
    if (!event.target.closest("#ai-setup")) dirty = true;
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    try {
      const payload = settingsPayload(form);
      if (
        payload.auto_save &&
        !values.auto_save &&
        !confirm(
          "검증을 통과한 영수증은 추가 확인 없이 가계부에 저장됩니다. 자동 저장을 켤까요?",
        )
      )
        return;
      btn.disabled = true;
      await api("/api/settings", payload);
      dirty = false;
      toast("설정을 저장했습니다. 다음 작업부터 적용됩니다.");
      await settings();
    } catch (err) {
      $("#settings-error").textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
}

function settingsStatusCard(status) {
  const missing = status.missing || [];
  const aside = card(
    "설정 준비 상태",
    el(
      "div",
      { class: "card-body" },
      missing.length
        ? el(
            "ul",
            { class: "setup-checklist" },
            ...missing.map((item) => el("li", {}, item)),
          )
        : el("p", {}, "필수 입력이 완료되었습니다."),
      el(
        "p",
        {},
        "저장한 설정을 기준으로 표시합니다. 실제 서버 연결·CLI 로그인·모델 설치 성공을 뜻하지는 않습니다.",
      ),
      el(
        "p",
        {},
        "접속 키는 비워 두면 기존 값을 유지합니다. 관리 비밀번호와 접속 키는 서로 다릅니다.",
      ),
    ),
  );
  aside.classList.add("settings-aside");
  return aside;
}

async function settings() {
  const data = await api("/api/settings");
  if (page !== "settings") return;
  const values = data.settings;
  setStatus(data.status);
  const content = $("#content");
  content.replaceChildren(
    head("서비스 설정", "내 환경에 맞게 연결과 영수증 처리 방식을 정하세요."),
  );
  const n = notice(data.status);
  if (n) content.append(n);
  const form = el("form", { id: "settings-form" });
  appendSettingsSections(form, values, data.secrets || {});
  configureAIFields(form, values);
  // Hidden settings keep their saved values; changing provider never enables external sending.
  form.append(
    el("p", { id: "settings-error", class: "error-message", role: "alert" }),
    el(
      "div",
      { class: "save-bar" },
      el(
        "small",
        {},
        "설정은 데이터 볼륨에 보관되며, 다음 작업부터 적용됩니다.\n실행 중인 작업은 현재 설정으로 마무리합니다.",
      ),
      el(
        "button",
        { type: "submit", class: "primary" },
        "변경 사항 저장",
        icon("check"),
      ),
    ),
  );
  bindSettingsSave(form, values);
  const aside = settingsStatusCard(data.status);
  content.append(el("div", { class: "settings-layout" }, form, aside));
  dirty = false;
}
