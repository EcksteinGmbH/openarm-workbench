export function buildConnectionPayload() {
    const transport = document.getElementById('transportType').value;
    if (transport === 'serial_bridge') {
        return {
            transport,
            connection: {
                serial_port: document.getElementById('serialPort').value.trim(),
                baudrate: Number(document.getElementById('serialBaudrate').value)
            }
        };
    }
    return {
        transport,
        connection: {
            channel: document.getElementById('socketcanChannel').value.trim(),
            bitrate: Number(document.getElementById('socketcanBitrate').value)
        }
    };
}

export function buildOverrides() {
    if (!document.getElementById('expertMode').checked) {
        return null;
    }
    return {
        target_esc_id: Number(document.getElementById('overrideEscId').value),
        target_mst_id: Number(document.getElementById('overrideMstId').value),
        target_ctrl_mode: document.getElementById('overrideCtrlMode').value,
        target_timeout: Number(document.getElementById('overrideTimeout').value),
        target_can_br: Number(document.getElementById('overrideCanBr').value)
    };
}
