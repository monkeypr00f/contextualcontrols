const CARD_TAG = "contextual-controls-card";

const TEXT = {
  en: {
    name: "Contextual Controls",
    description: "Shows the controls suggested by Contextual Controls.",
    defaultTitle: "For you now",
    morning: "Good morning",
    afternoon: "For you now",
    evening: "This evening",
    night: "Before sleep",
    empty: "No suggestions yet",
    missing: "Select a Contextual Controls sensor",
    updated: "Updated",
    sensor: "Sensor",
    title: "Title",
    maxControls: "Maximum controls",
    columns: "Desktop columns",
    mobileColumns: "Mobile columns",
    showState: "Show state",
    showReason: "Show reason",
    showScore: "Show score",
    showLastUpdate: "Show last update",
    hideEmpty: "Hide when empty",
    showPinned: "Show pinned controls",
    dynamicTitle: "Dynamic title",
    tapAction: "Tap action",
    automatic: "Automatic",
    toggle: "Toggle",
    moreInfo: "More info",
  },
  it: {
    name: "Contextual Controls",
    description: "Mostra i controlli suggeriti da Contextual Controls.",
    defaultTitle: "Per te adesso",
    morning: "Buongiorno",
    afternoon: "Per te adesso",
    evening: "Questa sera",
    night: "Prima di dormire",
    empty: "Nessun suggerimento per ora",
    missing: "Seleziona un sensore Contextual Controls",
    updated: "Aggiornato",
    sensor: "Sensore",
    title: "Titolo",
    maxControls: "Numero massimo di controlli",
    columns: "Colonne desktop",
    mobileColumns: "Colonne mobile",
    showState: "Mostra stato",
    showReason: "Mostra motivo",
    showScore: "Mostra punteggio",
    showLastUpdate: "Mostra ultimo aggiornamento",
    hideEmpty: "Nascondi se vuoto",
    showPinned: "Mostra controlli fissi",
    dynamicTitle: "Titolo dinamico",
    tapAction: "Azione al tocco",
    automatic: "Automatica",
    toggle: "Toggle",
    moreInfo: "Più informazioni",
  },
};

const TOGGLE_DOMAINS = new Set(["light", "switch", "fan", "input_boolean"]);
const MORE_INFO_DOMAINS = new Set([
  "alarm_control_panel",
  "climate",
  "cover",
  "lock",
  "media_player",
  "number",
  "select",
  "siren",
  "vacuum",
]);

function language() {
  return (navigator.language || "en").toLowerCase().startsWith("it") ? "it" : "en";
}

function t(key) {
  return TEXT[language()][key] || TEXT.en[key] || key;
}

function bool(config, key, fallback) {
  return config[key] === undefined ? fallback : Boolean(config[key]);
}

function domainOf(entityId) {
  return String(entityId || "").split(".", 1)[0];
}

function automaticAction(entityId) {
  const domain = domainOf(entityId);
  if (TOGGLE_DOMAINS.has(domain)) return { domain: "homeassistant", service: "toggle" };
  if (domain === "scene") return { domain: "scene", service: "turn_on" };
  if (domain === "script") return { domain: "script", service: "turn_on" };
  if (domain === "button") return { domain: "button", service: "press" };
  if (MORE_INFO_DOMAINS.has(domain)) return null;
  return null;
}

function defaultIcon(entityId) {
  const icons = {
    button: "mdi:gesture-tap-button",
    climate: "mdi:thermostat",
    cover: "mdi:window-shutter",
    fan: "mdi:fan",
    input_boolean: "mdi:toggle-switch",
    light: "mdi:lightbulb",
    lock: "mdi:lock",
    media_player: "mdi:cast",
    number: "mdi:numeric",
    scene: "mdi:palette",
    script: "mdi:script-text-play",
    select: "mdi:form-dropdown",
    switch: "mdi:toggle-switch",
    vacuum: "mdi:robot-vacuum",
  };
  return icons[domainOf(entityId)] || "mdi:gesture-tap-button";
}

function dynamicTitle(date = new Date()) {
  const hour = date.getHours();
  if (hour >= 6 && hour < 11) return t("morning");
  if (hour >= 11 && hour < 17) return t("afternoon");
  if (hour >= 17 && hour < 22) return t("evening");
  return t("night");
}

function fireMoreInfo(element, entityId) {
  element.dispatchEvent(
    new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId },
    }),
  );
}

class ContextualControlsCard extends HTMLElement {
  static getStubConfig() {
    return {
      sensor: "sensor.contextual_controls",
      title: t("defaultTitle"),
      columns: 3,
      mobile_columns: 2,
      show_state: true,
      show_reason: false,
      show_score: false,
      show_last_update: false,
      hide_empty: true,
      show_pinned: true,
      dynamic_title: false,
      tap_action: "automatic",
    };
  }

  static getConfigForm() {
    const labels = {
      sensor: "sensor",
      title: "title",
      max_controls: "maxControls",
      columns: "columns",
      mobile_columns: "mobileColumns",
      show_state: "showState",
      show_reason: "showReason",
      show_score: "showScore",
      show_last_update: "showLastUpdate",
      hide_empty: "hideEmpty",
      show_pinned: "showPinned",
      dynamic_title: "dynamicTitle",
      tap_action: "tapAction",
    };
    return {
      schema: [
        {
          name: "sensor",
          required: true,
          selector: { entity: { filter: { domain: "sensor" } } },
        },
        { name: "title", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          flatten: true,
          schema: [
            { name: "max_controls", selector: { number: { min: 1, max: 12, mode: "box" } } },
            { name: "columns", selector: { number: { min: 1, max: 6, mode: "box" } } },
            {
              name: "mobile_columns",
              selector: { number: { min: 1, max: 3, mode: "box" } },
            },
          ],
        },
        {
          name: "tap_action",
          selector: {
            select: {
              options: [
                { value: "automatic", label: t("automatic") },
                { value: "toggle", label: t("toggle") },
                { value: "more-info", label: t("moreInfo") },
              ],
            },
          },
        },
        {
          type: "grid",
          name: "",
          flatten: true,
          schema: [
            { name: "show_state", selector: { boolean: {} } },
            { name: "show_reason", selector: { boolean: {} } },
            { name: "show_score", selector: { boolean: {} } },
            { name: "show_last_update", selector: { boolean: {} } },
            { name: "hide_empty", selector: { boolean: {} } },
            { name: "show_pinned", selector: { boolean: {} } },
            { name: "dynamic_title", selector: { boolean: {} } },
          ],
        },
      ],
      computeLabel: (schema) => t(labels[schema.name] || schema.name),
      assertConfig: (config) => {
        if (!config.sensor || typeof config.sensor !== "string") {
          throw new Error(t("missing"));
        }
      },
    };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error(t("missing"));
    this._config = { ...ContextualControlsCard.getStubConfig(), ...config };
    this._signature = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const sensor = hass?.states?.[this._config?.sensor];
    const rows = Array.isArray(sensor?.attributes?.entities) ? sensor.attributes.entities : [];
    const visible = rows.filter((row) => bool(this._config, "show_pinned", true) || !row.pinned);
    const states = visible.map((row) => {
      const state = hass.states[row.entity_id];
      return [row.entity_id, state?.state, state?.attributes?.friendly_name, state?.attributes?.icon];
    });
    const signature = JSON.stringify([
      sensor?.state,
      sensor?.attributes?.last_update,
      visible,
      states,
      this._config,
    ]);
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    const count = this._visibleRows().length;
    const columns = Math.max(1, Number(this._config?.columns) || 3);
    return Math.max(1, Math.ceil(count / columns) * 2 + 1);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 2 };
  }

  _visibleRows() {
    const sensor = this._hass?.states?.[this._config?.sensor];
    const rows = Array.isArray(sensor?.attributes?.entities) ? sensor.attributes.entities : [];
    const filtered = rows.filter(
      (row) => bool(this._config, "show_pinned", true) || !Boolean(row.pinned),
    );
    const limit = Math.min(12, Math.max(1, Number(this._config?.max_controls) || 12));
    return filtered.slice(0, limit);
  }

  _title() {
    if (bool(this._config, "dynamic_title", false)) return dynamicTitle();
    return this._config?.title ?? t("defaultTitle");
  }

  _render() {
    if (!this._config) return;
    const sensor = this._hass?.states?.[this._config.sensor];
    const rows = this._visibleRows();
    if (sensor && rows.length === 0 && bool(this._config, "hide_empty", true)) {
      this.replaceChildren();
      return;
    }

    const card = document.createElement("ha-card");
    card.className = "cc-card";
    card.style.setProperty("--cc-columns", String(this._config.columns || 3));
    card.style.setProperty("--cc-mobile-columns", String(this._config.mobile_columns || 2));

    const style = document.createElement("style");
    style.textContent = `
      .cc-card { padding: 16px; }
      .cc-header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:0 0 14px; }
      .cc-title { color:var(--primary-text-color); font-size:20px; font-weight:500; line-height:1.25; }
      .cc-updated { color:var(--secondary-text-color); font-size:12px; white-space:nowrap; }
      .cc-grid { display:grid; grid-template-columns:repeat(var(--cc-columns), minmax(0, 1fr)); gap:10px; }
      .cc-tile { appearance:none; box-sizing:border-box; min-width:0; min-height:88px; padding:12px; border:0;
        border-radius:var(--ha-card-border-radius, 12px); color:var(--primary-text-color);
        background:var(--secondary-background-color); font:inherit; text-align:left; cursor:pointer;
        display:grid; grid-template-columns:38px minmax(0,1fr); column-gap:10px; align-items:center;
        transition:background-color .15s ease, transform .08s ease; }
      .cc-tile:hover { background:color-mix(in srgb, var(--secondary-background-color) 88%, var(--primary-color)); }
      .cc-tile:active { transform:scale(.985); }
      .cc-icon { width:38px; height:38px; border-radius:50%; display:grid; place-items:center;
        background:color-mix(in srgb, var(--primary-color) 16%, transparent); color:var(--primary-color); }
      .cc-icon ha-icon { --mdc-icon-size:22px; }
      .cc-copy { min-width:0; }
      .cc-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500; line-height:1.3; }
      .cc-state, .cc-reason, .cc-score { overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        color:var(--secondary-text-color); font-size:12px; line-height:1.35; }
      .cc-reason { margin-top:3px; white-space:normal; display:-webkit-box; -webkit-line-clamp:2;
        -webkit-box-orient:vertical; }
      .cc-empty, .cc-missing { color:var(--secondary-text-color); padding:8px 0 2px; }
      @media (max-width:600px) {
        .cc-card { padding:14px; }
        .cc-grid { grid-template-columns:repeat(var(--cc-mobile-columns), minmax(0, 1fr)); gap:8px; }
        .cc-tile { min-height:82px; padding:10px; grid-template-columns:34px minmax(0,1fr); column-gap:8px; }
        .cc-icon { width:34px; height:34px; }
      }
    `;
    card.append(style);

    const title = this._title();
    if (title || bool(this._config, "show_last_update", false)) {
      const header = document.createElement("div");
      header.className = "cc-header";
      const heading = document.createElement("div");
      heading.className = "cc-title";
      heading.textContent = title;
      header.append(heading);
      const updated = sensor?.attributes?.last_update;
      if (updated && bool(this._config, "show_last_update", false)) {
        const timestamp = document.createElement("div");
        timestamp.className = "cc-updated";
        timestamp.textContent = `${t("updated")} ${new Intl.DateTimeFormat(language(), {
          hour: "2-digit",
          minute: "2-digit",
        }).format(new Date(updated))}`;
        header.append(timestamp);
      }
      card.append(header);
    }

    if (!sensor) {
      const missing = document.createElement("div");
      missing.className = "cc-missing";
      missing.textContent = t("missing");
      card.append(missing);
    } else if (rows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "cc-empty";
      empty.textContent = t("empty");
      card.append(empty);
    } else {
      const grid = document.createElement("div");
      grid.className = "cc-grid";
      for (const row of rows) grid.append(this._tile(row));
      card.append(grid);
    }
    this.replaceChildren(card);
  }

  _tile(row) {
    const entityId = row.entity_id;
    const stateObj = this._hass?.states?.[entityId];
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "cc-tile";
    tile.title = stateObj?.attributes?.friendly_name || entityId;
    tile.setAttribute("aria-label", stateObj?.attributes?.friendly_name || entityId);

    const iconWrap = document.createElement("span");
    iconWrap.className = "cc-icon";
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", stateObj?.attributes?.icon || defaultIcon(entityId));
    iconWrap.append(icon);

    const copy = document.createElement("span");
    copy.className = "cc-copy";
    const name = document.createElement("div");
    name.className = "cc-name";
    name.textContent = stateObj?.attributes?.friendly_name || entityId;
    copy.append(name);
    if (bool(this._config, "show_state", true) && stateObj) {
      const state = document.createElement("div");
      state.className = "cc-state";
      state.textContent = this._hass?.formatEntityState?.(stateObj) || stateObj.state;
      copy.append(state);
    }
    if (bool(this._config, "show_reason", false) && row.reason) {
      const reason = document.createElement("div");
      reason.className = "cc-reason";
      reason.textContent = row.reason;
      copy.append(reason);
    }
    if (bool(this._config, "show_score", false) && Number.isFinite(Number(row.score))) {
      const score = document.createElement("div");
      score.className = "cc-score";
      score.textContent = `${Math.round(Number(row.score) * 100)}%`;
      copy.append(score);
    }
    tile.append(iconWrap, copy);

    let held = false;
    let timer;
    tile.addEventListener("pointerdown", () => {
      held = false;
      timer = window.setTimeout(() => {
        held = true;
        fireMoreInfo(this, entityId);
      }, 550);
    });
    for (const eventName of ["pointerup", "pointercancel", "pointerleave"]) {
      tile.addEventListener(eventName, () => window.clearTimeout(timer));
    }
    tile.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      fireMoreInfo(this, entityId);
    });
    tile.addEventListener("click", () => {
      if (held) {
        held = false;
        return;
      }
      this._tap(entityId);
    });
    return tile;
  }

  _tap(entityId) {
    const configured = this._config.tap_action || "automatic";
    if (configured === "more-info") {
      fireMoreInfo(this, entityId);
      return;
    }
    let action = automaticAction(entityId);
    if (configured === "toggle") {
      action = TOGGLE_DOMAINS.has(domainOf(entityId))
        ? { domain: "homeassistant", service: "toggle" }
        : automaticAction(entityId);
    }
    if (!action) {
      fireMoreInfo(this, entityId);
      return;
    }
    this._hass.callService(action.domain, action.service, { entity_id: entityId });
  }
}

if (!customElements.get(CARD_TAG)) customElements.define(CARD_TAG, ContextualControlsCard);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: t("name"),
    description: t("description"),
    preview: true,
    documentationURL: "https://github.com/monkeypr00f/contextualcontrols",
    getEntitySuggestion: (_hass, entityId) =>
      entityId.startsWith("sensor.contextual_controls")
        ? { config: { type: `custom:${CARD_TAG}`, sensor: entityId } }
        : null,
  });
}
