/** @odoo-module */

import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useRef } from "@odoo/owl";

const DEFAULT_COLOR = "#e9ecef";
const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;

function cssColorToHex(value) {
    if (!window.CSS?.supports?.("color", value)) {
        return DEFAULT_COLOR;
    }
    const colorProbe = document.createElement("span");
    colorProbe.style.color = value;
    document.body.appendChild(colorProbe);
    const computedColor = getComputedStyle(colorProbe).color;
    colorProbe.remove();

    const rgbMatch = computedColor.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (!rgbMatch) {
        return DEFAULT_COLOR;
    }
    return `#${rgbMatch
        .slice(1, 4)
        .map((channel) => Number(channel).toString(16).padStart(2, "0"))
        .join("")}`;
}

function normalizeColor(value) {
    const color = String(value || "").trim();
    if (/^#[0-9a-f]{3}$/i.test(color)) {
        return `#${color[1]}${color[1]}${color[2]}${color[2]}${color[3]}${color[3]}`.toLowerCase();
    }
    if (HEX_COLOR_RE.test(color)) {
        return color.toLowerCase();
    }
    return cssColorToHex(color);
}

export class PosUIColorPickerField extends Component {
    static template = "pos_ui_layout_engine.ColorPickerField";
    static props = standardFieldProps;

    setup() {
        this.input = useRef("input");
        useInputField({
            getValue: () => normalizeColor(this.props.record.data[this.props.name]),
            parse: (value) => normalizeColor(value),
        });
    }

    get colorValue() {
        return normalizeColor(this.props.record.data[this.props.name]);
    }

    async onColorInput(ev) {
        await this.props.record.update({
            [this.props.name]: normalizeColor(ev.target.value),
        });
    }
}

export const posUIColorPickerField = {
    component: PosUIColorPickerField,
    displayName: "POS UI Color Picker",
    supportedTypes: ["char"],
};

registry.category("fields").add("pos_ui_color_picker", posUIColorPickerField);
