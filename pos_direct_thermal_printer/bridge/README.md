# Odoo POS Local Print Bridge

Run this bridge on the till PC where Chrome opens Odoo POS.

## Start

```bat
RUN_BRIDGE_POS80.bat
```

## Install As Windows Service

Run as Administrator:

```bat
INSTALL_WINDOWS_SERVICE.bat
```

Service name:

```text
OdooPOSPrintBridge
```

Logs:

```text
C:\pos_print_bridge\logs
```

Remove service:

```bat
REMOVE_WINDOWS_SERVICE.bat
```

## Health Check

Open:

```text
http://127.0.0.1:9109/health
```

Expected:

```json
{
  "ok": true
}
```

## Printers

Open:

```text
http://127.0.0.1:9109/printers
```

Use the exact printer name in Odoo POS `Printer Identifier`, or leave that field empty to use the Windows default printer on the till PC.
