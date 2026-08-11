/* @ds-bundle: {"format":4,"namespace":"ORCADesignSystem_bf9362","components":[{"name":"Button","sourcePath":"components/controls/Button.jsx"},{"name":"Checkbox","sourcePath":"components/controls/Checkbox.jsx"},{"name":"Icon","sourcePath":"components/controls/Icon.jsx"},{"name":"Label","sourcePath":"components/controls/Label.jsx"},{"name":"MultiSelect","sourcePath":"components/controls/MultiSelect.jsx"},{"name":"NumberInput","sourcePath":"components/controls/NumberInput.jsx"},{"name":"RadioGroup","sourcePath":"components/controls/RadioGroup.jsx"},{"name":"Select","sourcePath":"components/controls/Select.jsx"},{"name":"Slider","sourcePath":"components/controls/Slider.jsx"},{"name":"CodeBlock","sourcePath":"components/data/CodeBlock.jsx"},{"name":"DataTable","sourcePath":"components/data/DataTable.jsx"},{"name":"MapLegend","sourcePath":"components/data/MapLegend.jsx"},{"name":"RainBarChart","sourcePath":"components/data/RainBarChart.jsx"},{"name":"RISK_COLORS","sourcePath":"components/data/RiskBadge.jsx"},{"name":"RiskBadge","sourcePath":"components/data/RiskBadge.jsx"},{"name":"Callout","sourcePath":"components/feedback/Callout.jsx"},{"name":"Spinner","sourcePath":"components/feedback/Spinner.jsx"},{"name":"Caption","sourcePath":"components/layout/Caption.jsx"},{"name":"PageHeader","sourcePath":"components/layout/PageHeader.jsx"},{"name":"SectionHeading","sourcePath":"components/layout/SectionHeading.jsx"},{"name":"SidebarSection","sourcePath":"components/layout/SidebarSection.jsx"}],"sourceHashes":{"components/controls/Button.jsx":"a2368a9a3264","components/controls/Checkbox.jsx":"2705a9196522","components/controls/Icon.jsx":"c48471846818","components/controls/Label.jsx":"3f6c680156dd","components/controls/MultiSelect.jsx":"edda11765c8b","components/controls/NumberInput.jsx":"e0daf998b1bc","components/controls/RadioGroup.jsx":"896331e21950","components/controls/Select.jsx":"ac445cd6eaea","components/controls/Slider.jsx":"4437ad06d833","components/data/CodeBlock.jsx":"2f6f3b59f396","components/data/DataTable.jsx":"fe7f65418a83","components/data/MapLegend.jsx":"e25ab8302016","components/data/RainBarChart.jsx":"b65a7c27872a","components/data/RiskBadge.jsx":"6a0f7ad4d1e0","components/feedback/Callout.jsx":"457405feced1","components/feedback/Spinner.jsx":"68446038e67f","components/layout/Caption.jsx":"d2c9ad377451","components/layout/PageHeader.jsx":"c0875277745c","components/layout/SectionHeading.jsx":"9350faf66ce3","components/layout/SidebarSection.jsx":"aa012b0f7ef8","ui_kits/dashboard/App.jsx":"a717746229d3","ui_kits/dashboard/AttentionPanel.jsx":"40b2ad5d8742","ui_kits/dashboard/MapPanel.jsx":"68c5fd458ef4","ui_kits/dashboard/SeriesPanel.jsx":"bf3adb4dfa50","ui_kits/dashboard/Sidebar.jsx":"f0007bfe3416","ui_kits/dashboard/data.js":"1b537b77ce0b"},"inlinedExternals":[],"unexposedExports":[{"name":"riskColor","sourcePath":"components/data/RiskBadge.jsx"}]} */

(() => {

const __ds_ns = (window.ORCADesignSystem_bf9362 = window.ORCADesignSystem_bf9362 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/controls/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const orcaButtonBase = {
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-label)',
  fontWeight: 'var(--weight-regular)',
  lineHeight: 'var(--leading-snug)',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 'var(--space-2)',
  padding: '0 var(--space-3)',
  minHeight: 'var(--control-height)',
  borderRadius: 'var(--radius-lg)',
  borderStyle: 'solid',
  borderWidth: 'var(--border-hairline)',
  cursor: 'pointer',
  transition: 'var(--transition-fast)',
  userSelect: 'none',
  whiteSpace: 'nowrap'
};
const orcaButtonVariants = {
  secondary: {
    background: 'var(--surface-card)',
    color: 'var(--text-body)',
    borderColor: 'var(--border-input)'
  },
  primary: {
    background: 'var(--accent)',
    color: 'var(--text-on-dark)',
    borderColor: 'var(--accent)'
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-body)',
    borderColor: 'transparent'
  }
};
function Button({
  children,
  variant = 'secondary',
  icon,
  iconEnd,
  fullWidth = false,
  disabled = false,
  onClick,
  style,
  ...rest
}) {
  const [hover, setHover] = React.useState(false);
  const hoverStyle = !disabled && hover ? variant === 'primary' ? {
    background: 'var(--accent-press)',
    borderColor: 'var(--accent-press)'
  } : {
    color: 'var(--accent)',
    borderColor: 'var(--accent)'
  } : null;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    disabled: disabled,
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      ...orcaButtonBase,
      ...orcaButtonVariants[variant],
      width: fullWidth ? '100%' : 'auto',
      opacity: disabled ? 0.4 : 1,
      cursor: disabled ? 'not-allowed' : 'pointer',
      ...hoverStyle,
      ...style
    }
  }, rest), icon, children, iconEnd);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Button.jsx", error: String((e && e.message) || e) }); }

// components/controls/Icon.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Material Symbols Rounded — the icon font Streamlit renders. Loaded by
   tokens/fonts.css; no icon assets exist in the ORCA repo itself. */
function Icon({
  name,
  size = 20,
  weight = 400,
  fill = 0,
  color = 'currentColor',
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    className: "material-symbols-rounded",
    "aria-hidden": "true",
    style: {
      fontFamily: 'var(--font-icon)',
      fontSize: size,
      lineHeight: 1,
      color,
      fontVariationSettings: `'FILL' ${fill}, 'wght' ${weight}, 'GRAD' 0, 'opsz' ${size}`,
      ...style
    }
  }, rest), name);
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Icon.jsx", error: String((e && e.message) || e) }); }

// components/controls/Checkbox.jsx
try { (() => {
function Checkbox({
  label,
  checked = false,
  onChange,
  help,
  style
}) {
  return /*#__PURE__*/React.createElement("label", {
    onClick: () => onChange && onChange(!checked),
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 'var(--space-2)',
      cursor: 'pointer',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: 'var(--text-body)',
      lineHeight: 'var(--leading-snug)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 16,
      height: 16,
      flex: '0 0 auto',
      marginTop: 2,
      borderRadius: 'var(--radius-sm)',
      background: checked ? 'var(--accent)' : 'var(--paper-2)',
      border: checked ? 'none' : 'var(--border-hairline) solid var(--border-input)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, checked && /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "check",
    size: 14,
    color: "var(--paper-1)",
    weight: 500
  })), /*#__PURE__*/React.createElement("span", null, label), help && /*#__PURE__*/React.createElement("span", {
    title: help,
    style: {
      display: 'inline-flex',
      marginTop: 2
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "help",
    size: 16,
    color: "var(--ink-4)"
  })));
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/controls/Label.jsx
try { (() => {
function Label({
  children,
  help,
  style
}) {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      marginBottom: 'var(--space-1)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: 'var(--text-body)',
      lineHeight: 'var(--leading-snug)',
      ...style
    }
  }, children, help && /*#__PURE__*/React.createElement("span", {
    title: help,
    style: {
      display: 'inline-flex',
      cursor: 'help'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "help",
    size: 16,
    color: "var(--ink-4)"
  })));
}
Object.assign(__ds_scope, { Label });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Label.jsx", error: String((e && e.message) || e) }); }

// components/controls/MultiSelect.jsx
try { (() => {
function MultiSelect({
  label,
  options = [],
  value = [],
  onChange,
  placeholder = 'Choose options',
  help,
  style
}) {
  const [open, setOpen] = React.useState(false);
  const toggle = v => {
    const next = value.includes(v) ? value.filter(x => x !== v) : [...value, v];
    onChange && onChange(next);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement(__ds_scope.Label, {
    help: help
  }, label), /*#__PURE__*/React.createElement("div", {
    onClick: () => setOpen(o => !o),
    style: {
      width: '100%',
      minHeight: 'var(--control-height)',
      display: 'flex',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: 'var(--space-1)',
      padding: 'var(--space-1) var(--space-3)',
      background: 'var(--surface-card)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      cursor: 'pointer'
    }
  }, value.length === 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--text-label)',
      color: 'var(--text-caption)'
    }
  }, placeholder), value.map(v => /*#__PURE__*/React.createElement("span", {
    key: v,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      background: 'var(--paper-2)',
      borderRadius: 'var(--radius-sm)',
      padding: '2px var(--space-1) 2px var(--space-2)',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-body)'
    }
  }, v, /*#__PURE__*/React.createElement("span", {
    onClick: e => {
      e.stopPropagation();
      toggle(v);
    },
    style: {
      display: 'inline-flex'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "close",
    size: 14,
    color: "var(--ink-3)"
  })))), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      display: 'inline-flex'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: open ? 'expand_less' : 'expand_more',
    size: 20,
    color: "var(--ink-3)"
  }))), open && /*#__PURE__*/React.createElement("ul", {
    style: {
      position: 'absolute',
      zIndex: 20,
      top: 'calc(100% + 4px)',
      left: 0,
      right: 0,
      margin: 0,
      padding: 'var(--space-1) 0',
      listStyle: 'none',
      background: 'var(--surface-card)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: 'var(--shadow-popover)',
      maxHeight: 220,
      overflowY: 'auto'
    }
  }, options.filter(o => !value.includes(o)).map(o => /*#__PURE__*/React.createElement("li", {
    key: o
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => toggle(o),
    style: {
      display: 'block',
      width: '100%',
      textAlign: 'left',
      border: 'none',
      background: 'transparent',
      cursor: 'pointer',
      padding: 'var(--space-2) var(--space-3)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: 'var(--text-body)'
    }
  }, o)))));
}
Object.assign(__ds_scope, { MultiSelect });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/MultiSelect.jsx", error: String((e && e.message) || e) }); }

// components/controls/NumberInput.jsx
try { (() => {
function NumberInput({
  label,
  value,
  onChange,
  min = -Infinity,
  max = Infinity,
  step = 1,
  help,
  style
}) {
  const clamp = n => Math.min(max, Math.max(min, n));
  const stepper = {
    width: 34,
    minHeight: 'calc(var(--control-height) - 2px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: 'none',
    borderLeft: 'var(--border-hairline) solid var(--border-input)',
    background: 'var(--surface-card)',
    cursor: 'pointer'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement(__ds_scope.Label, {
    help: help
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'stretch',
      background: 'var(--surface-card)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: value,
    onChange: e => onChange && onChange(Number(e.target.value)),
    style: {
      flex: 1,
      minWidth: 0,
      border: 'none',
      outline: 'none',
      background: 'transparent',
      padding: '0 var(--space-3)',
      minHeight: 'calc(var(--control-height) - 2px)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: 'var(--text-body)'
    }
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    style: stepper,
    onClick: () => onChange && onChange(clamp(Number(value) - step))
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "remove",
    size: 16,
    color: "var(--ink-3)"
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    style: stepper,
    onClick: () => onChange && onChange(clamp(Number(value) + step))
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "add",
    size: 16,
    color: "var(--ink-3)"
  }))));
}
Object.assign(__ds_scope, { NumberInput });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/NumberInput.jsx", error: String((e && e.message) || e) }); }

// components/controls/RadioGroup.jsx
try { (() => {
function RadioGroup({
  label,
  options = [],
  value,
  onChange,
  direction = 'column',
  help,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement(__ds_scope.Label, {
    help: help
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: direction,
      gap: direction === 'row' ? 'var(--space-5)' : 'var(--space-2)'
    }
  }, options.map(o => {
    const v = o.value ?? o;
    const on = v === value;
    return /*#__PURE__*/React.createElement("label", {
      key: v,
      onClick: () => onChange && onChange(v),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        cursor: 'pointer',
        fontSize: 'var(--text-label)',
        color: 'var(--text-body)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 16,
        height: 16,
        borderRadius: 'var(--radius-pill)',
        flex: '0 0 auto',
        background: on ? 'var(--accent)' : 'var(--paper-2)',
        border: on ? 'none' : 'var(--border-hairline) solid var(--border-input)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, on && /*#__PURE__*/React.createElement("span", {
      style: {
        width: 6,
        height: 6,
        borderRadius: 'var(--radius-pill)',
        background: 'var(--paper-1)'
      }
    })), o.label ?? o);
  })));
}
Object.assign(__ds_scope, { RadioGroup });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/RadioGroup.jsx", error: String((e && e.message) || e) }); }

// components/controls/Select.jsx
try { (() => {
function Select({
  label,
  options = [],
  value,
  onChange,
  placeholder = 'Choose an option',
  help,
  style
}) {
  const [open, setOpen] = React.useState(false);
  const current = options.find(o => (o.value ?? o) === value);
  const currentLabel = current ? current.label ?? current : null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement(__ds_scope.Label, {
    help: help
  }, label), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setOpen(o => !o),
    style: {
      width: '100%',
      minHeight: 'var(--control-height)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-2)',
      padding: '0 var(--space-3)',
      background: 'var(--surface-card)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: currentLabel ? 'var(--text-body)' : 'var(--text-caption)',
      cursor: 'pointer',
      textAlign: 'left'
    }
  }, /*#__PURE__*/React.createElement("span", null, currentLabel ?? placeholder), /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: open ? 'expand_less' : 'expand_more',
    size: 20,
    color: "var(--ink-3)"
  })), open && /*#__PURE__*/React.createElement("ul", {
    style: {
      position: 'absolute',
      zIndex: 20,
      top: 'calc(100% + 4px)',
      left: 0,
      right: 0,
      margin: 0,
      padding: 'var(--space-1) 0',
      listStyle: 'none',
      background: 'var(--surface-card)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: 'var(--shadow-popover)',
      maxHeight: 240,
      overflowY: 'auto'
    }
  }, options.map(o => {
    const v = o.value ?? o;
    return /*#__PURE__*/React.createElement("li", {
      key: v
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      onClick: () => {
        onChange && onChange(v);
        setOpen(false);
      },
      style: {
        display: 'block',
        width: '100%',
        textAlign: 'left',
        border: 'none',
        background: v === value ? 'var(--paper-2)' : 'transparent',
        cursor: 'pointer',
        padding: 'var(--space-2) var(--space-3)',
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--text-label)',
        color: 'var(--text-body)'
      }
    }, o.label ?? o));
  })));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Select.jsx", error: String((e && e.message) || e) }); }

// components/controls/Slider.jsx
try { (() => {
function Slider({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  showBounds = true,
  help,
  style
}) {
  const pct = (value - min) / (max - min) * 100;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement(__ds_scope.Label, {
    help: help
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      height: 22
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      left: `${pct}%`,
      transform: 'translateX(-50%)',
      top: 0,
      fontSize: 'var(--text-caption)',
      color: 'var(--accent)',
      fontFamily: 'var(--font-ui)',
      whiteSpace: 'nowrap'
    }
  }, value, unit)), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      height: 20,
      display: 'flex',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      right: 0,
      height: 4,
      borderRadius: 'var(--radius-pill)',
      background: 'var(--line-2)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      width: `${pct}%`,
      height: 4,
      borderRadius: 'var(--radius-pill)',
      background: 'var(--accent)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: `${pct}%`,
      transform: 'translateX(-50%)',
      width: 15,
      height: 15,
      borderRadius: 'var(--radius-pill)',
      background: 'var(--accent)'
    }
  }), /*#__PURE__*/React.createElement("input", {
    type: "range",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange && onChange(Number(e.target.value)),
    style: {
      position: 'absolute',
      left: 0,
      right: 0,
      width: '100%',
      margin: 0,
      opacity: 0,
      height: 20,
      cursor: 'pointer'
    }
  })), showBounds && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-caption)'
    }
  }, /*#__PURE__*/React.createElement("span", null, min), /*#__PURE__*/React.createElement("span", null, max)));
}
Object.assign(__ds_scope, { Slider });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/controls/Slider.jsx", error: String((e && e.message) || e) }); }

// components/data/CodeBlock.jsx
try { (() => {
function CodeBlock({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("pre", {
    style: {
      margin: 0,
      padding: 'var(--space-3)',
      background: 'var(--surface-input)',
      border: 'var(--border-hairline) solid var(--border-input)',
      borderRadius: 'var(--radius-lg)',
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-body)',
      lineHeight: 'var(--leading-snug)',
      overflowX: 'auto',
      whiteSpace: 'pre',
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { CodeBlock });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/CodeBlock.jsx", error: String((e && e.message) || e) }); }

// components/data/DataTable.jsx
try { (() => {
function DataTable({
  columns = [],
  rows = [],
  showIndex = true,
  maxHeight,
  style
}) {
  const cell = {
    padding: 'var(--space-2) var(--space-3)',
    fontFamily: 'var(--font-ui)',
    fontSize: 'var(--text-label)',
    color: 'var(--text-body)',
    borderBottom: 'var(--border-hairline) solid var(--border-table)',
    borderRight: 'var(--border-hairline) solid var(--border-table)',
    whiteSpace: 'nowrap'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      border: 'var(--border-hairline) solid var(--border-table)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'auto',
      maxHeight,
      background: 'var(--surface-card)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      borderCollapse: 'collapse',
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, showIndex && /*#__PURE__*/React.createElement("th", {
    style: {
      ...cell,
      background: 'var(--surface-table-head)',
      width: 44
    }
  }), columns.map(c => /*#__PURE__*/React.createElement("th", {
    key: c.key ?? c,
    style: {
      ...cell,
      background: 'var(--surface-table-head)',
      color: 'var(--text-muted)',
      fontWeight: 'var(--weight-regular)',
      textAlign: c.align === 'right' ? 'right' : 'left'
    }
  }, c.label ?? c)))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, showIndex && /*#__PURE__*/React.createElement("td", {
    style: {
      ...cell,
      background: 'var(--surface-table-head)',
      color: 'var(--text-muted)',
      textAlign: 'right'
    }
  }, i), columns.map(c => {
    const k = c.key ?? c;
    return /*#__PURE__*/React.createElement("td", {
      key: k,
      style: {
        ...cell,
        textAlign: c.align === 'right' ? 'right' : 'left',
        fontFamily: c.mono ? 'var(--font-mono)' : 'var(--font-ui)'
      }
    }, c.render ? c.render(r) : r[k]);
  }))))));
}
Object.assign(__ds_scope, { DataTable });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/DataTable.jsx", error: String((e && e.message) || e) }); }

// components/data/MapLegend.jsx
try { (() => {
/* Reproduces the legend HTML injected into the Folium map in src/dashboard/app.py:
   white card, 10px 14px padding, 6px radius, 0 1px 4px rgba(0,0,0,0.3), 13px text. */
function MapLegend({
  title = 'Grau de risco',
  items,
  floating = false,
  style
}) {
  const rows = items || [{
    color: 'var(--risk-high)',
    label: 'Alto'
  }, {
    color: 'var(--risk-very-high)',
    label: 'Muito alto'
  }, {
    outline: true,
    label: 'Em atenção (chuva acima do limiar)'
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: 'var(--surface-card)',
      padding: '10px 14px',
      borderRadius: 'var(--radius-md)',
      boxShadow: 'var(--shadow-legend)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-body)',
      display: 'inline-block',
      ...(floating ? {
        position: 'absolute',
        bottom: 30,
        left: 30,
        zIndex: 1000
      } : null),
      ...style
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      fontWeight: 'var(--weight-semibold)'
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
      marginTop: 2
    }
  }, rows.map(r => /*#__PURE__*/React.createElement("span", {
    key: r.label,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 10,
      height: 10,
      flex: '0 0 auto',
      background: r.outline ? 'var(--paper-1)' : r.color,
      border: r.outline ? 'var(--border-emphasis) solid var(--map-outline-attention)' : 'none'
    }
  }), r.label))));
}
Object.assign(__ds_scope, { MapLegend });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/MapLegend.jsx", error: String((e && e.message) || e) }); }

// components/data/RainBarChart.jsx
try { (() => {
/* Hourly rainfall bars — the Plotly figure in src/dashboard/app.py
   (marker_color = COR_CHUVA, height 350, axis titles in Portuguese). */
function RainBarChart({
  data = [],
  height = 350,
  xTitle = 'Data/hora (UTC)',
  yTitle = 'Chuva horária (mm)',
  style
}) {
  const max = Math.max(1, ...data.map(d => d.value || 0));
  const ticks = [0, max / 2, max];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-ui)',
      display: 'flex',
      gap: 'var(--space-2)',
      height,
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      writingMode: 'vertical-rl',
      transform: 'rotate(180deg)',
      fontSize: 'var(--text-micro)',
      color: 'var(--text-muted)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, yTitle), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'space-between',
      fontSize: 'var(--text-micro)',
      color: 'var(--text-caption)',
      paddingBottom: 22,
      textAlign: 'right'
    }
  }, [...ticks].reverse().map(t => /*#__PURE__*/React.createElement("span", {
    key: t
  }, t.toFixed(t < 10 ? 1 : 0)))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      alignItems: 'flex-end',
      gap: 1,
      borderLeft: 'var(--border-hairline) solid var(--line-1)',
      borderBottom: 'var(--border-hairline) solid var(--line-1)',
      padding: '0 2px'
    }
  }, data.map((d, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    title: `${d.label}: ${d.value} mm`,
    style: {
      flex: 1,
      minWidth: 1,
      height: `${(d.value || 0) / max * 100}%`,
      background: 'var(--rain-500)'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      fontSize: 'var(--text-micro)',
      color: 'var(--text-caption)',
      paddingTop: 4
    }
  }, /*#__PURE__*/React.createElement("span", null, data[0] && data[0].label), /*#__PURE__*/React.createElement("span", null, data.length > 1 && data[data.length - 1].label)), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      fontSize: 'var(--text-micro)',
      color: 'var(--text-muted)'
    }
  }, xTitle)));
}
Object.assign(__ds_scope, { RainBarChart });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/RainBarChart.jsx", error: String((e && e.message) || e) }); }

// components/data/RiskBadge.jsx
try { (() => {
/* Grau de risco — colour, mirroring CORES_GRAU_RISCO / COR_PADRAO in
   src/dashboard/app.py. Lookup is case-insensitive and trimmed, as in _cor_por_grau. */
const RISK_COLORS = {
  'alto': 'var(--risk-high)',
  'muito alto': 'var(--risk-very-high)'
};
function riskColor(grau) {
  if (!grau) return 'var(--risk-unknown)';
  return RISK_COLORS[String(grau).trim().toLowerCase()] || 'var(--risk-unknown)';
}
function RiskBadge({
  grau,
  attention = false,
  showLabel = true,
  size = 11,
  style
}) {
  const cor = riskColor(grau);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-body)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      flex: '0 0 auto',
      background: cor,
      border: attention ? 'var(--border-emphasis) solid var(--map-outline-attention)' : 'none'
    }
  }), showLabel && (grau || 'Não informado'));
}
Object.assign(__ds_scope, { RISK_COLORS, riskColor, RiskBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/RiskBadge.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Callout.jsx
try { (() => {
const orcaCalloutTones = {
  info: {
    background: 'var(--info-bg)',
    color: 'var(--info-fg)'
  },
  warning: {
    background: 'var(--warn-bg)',
    color: 'var(--warn-fg)'
  },
  success: {
    background: 'var(--ok-bg)',
    color: 'var(--ok-fg)'
  },
  error: {
    background: 'var(--error-bg)',
    color: 'var(--error-fg)'
  }
};
function Callout({
  children,
  tone = 'info',
  icon,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)',
      alignItems: 'flex-start',
      padding: 'var(--space-4)',
      borderRadius: 'var(--radius-lg)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-body)',
      lineHeight: 'var(--leading-normal)',
      ...orcaCalloutTones[tone],
      ...style
    }
  }, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      flex: '0 0 auto',
      marginTop: 2
    }
  }, icon), /*#__PURE__*/React.createElement("div", null, children));
}
Object.assign(__ds_scope, { Callout });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Callout.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Spinner.jsx
try { (() => {
function Spinner({
  label,
  size = 20,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-label)',
      color: 'var(--text-muted)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("style", null, '@keyframes orcaSpin{to{transform:rotate(360deg)}}'), /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      flex: '0 0 auto',
      borderRadius: 'var(--radius-pill)',
      border: '2px solid var(--line-2)',
      borderTopColor: 'var(--accent)',
      animation: 'orcaSpin 700ms linear infinite'
    }
  }), label);
}
Object.assign(__ds_scope, { Spinner });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Spinner.jsx", error: String((e && e.message) || e) }); }

// components/layout/Caption.jsx
try { (() => {
function Caption({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-caption)',
      lineHeight: 'var(--leading-loose)',
      textWrap: 'pretty',
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Caption });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/layout/Caption.jsx", error: String((e && e.message) || e) }); }

// components/layout/PageHeader.jsx
try { (() => {
function PageHeader({
  title,
  caption,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      fontFamily: 'var(--font-ui)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--text-display)',
      fontWeight: 'var(--weight-bold)',
      color: 'var(--text-title)',
      lineHeight: 'var(--leading-tight)',
      letterSpacing: 'var(--tracking-tight)'
    }
  }, title), caption && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 'var(--space-3) 0 0',
      fontSize: 'var(--text-caption)',
      color: 'var(--text-caption)',
      lineHeight: 'var(--leading-loose)',
      maxWidth: '80ch',
      textWrap: 'pretty'
    }
  }, caption), children);
}
Object.assign(__ds_scope, { PageHeader });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/layout/PageHeader.jsx", error: String((e && e.message) || e) }); }

// components/layout/SectionHeading.jsx
try { (() => {
function SectionHeading({
  children,
  count,
  level = 2,
  style
}) {
  const Tag = `h${level}`;
  return /*#__PURE__*/React.createElement(Tag, {
    style: {
      margin: 0,
      fontFamily: 'var(--font-ui)',
      fontSize: level === 2 ? 'var(--text-h2)' : 'var(--text-h3)',
      fontWeight: 'var(--weight-semibold)',
      color: 'var(--text-title)',
      lineHeight: 'var(--leading-snug)',
      ...style
    }
  }, children, count != null && ` — ${count}`);
}
Object.assign(__ds_scope, { SectionHeading });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/layout/SectionHeading.jsx", error: String((e && e.message) || e) }); }

// components/layout/SidebarSection.jsx
try { (() => {
function SidebarSection({
  title,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      ...style
    }
  }, title && /*#__PURE__*/React.createElement(__ds_scope.SectionHeading, {
    level: 3
  }, title), children);
}
Object.assign(__ds_scope, { SidebarSection });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/layout/SidebarSection.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.Label = __ds_scope.Label;

__ds_ns.MultiSelect = __ds_scope.MultiSelect;

__ds_ns.NumberInput = __ds_scope.NumberInput;

__ds_ns.RadioGroup = __ds_scope.RadioGroup;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Slider = __ds_scope.Slider;

__ds_ns.CodeBlock = __ds_scope.CodeBlock;

__ds_ns.DataTable = __ds_scope.DataTable;

__ds_ns.MapLegend = __ds_scope.MapLegend;

__ds_ns.RainBarChart = __ds_scope.RainBarChart;

__ds_ns.RISK_COLORS = __ds_scope.RISK_COLORS;

__ds_ns.RiskBadge = __ds_scope.RiskBadge;

__ds_ns.Callout = __ds_scope.Callout;

__ds_ns.Spinner = __ds_scope.Spinner;

__ds_ns.Caption = __ds_scope.Caption;

__ds_ns.PageHeader = __ds_scope.PageHeader;

__ds_ns.SectionHeading = __ds_scope.SectionHeading;

__ds_ns.SidebarSection = __ds_scope.SidebarSection;

})();
