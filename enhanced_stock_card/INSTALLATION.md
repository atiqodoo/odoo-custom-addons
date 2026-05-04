# Installation Guide - Enhanced Stock Card Report

## Quick Installation Steps

### 1. Extract the Module
Extract the ZIP file to get the `enhanced_stock_card` folder.

### 2. Copy to Odoo Addons
Copy the entire `enhanced_stock_card` folder to your Odoo addons directory:

**Linux/Mac:**
```bash
sudo cp -r enhanced_stock_card /opt/odoo/addons/
# or your custom addons path
sudo cp -r enhanced_stock_card /path/to/your/custom_addons/
```

**Windows:**
```
Copy the folder to: C:\Program Files\Odoo 18\server\odoo\addons\
or your custom addons path
```

### 3. Install Python Dependencies
The module requires xlsxwriter for Excel export:

```bash
pip install xlsxwriter
# or
pip3 install xlsxwriter
```

For Odoo installed via package manager:
```bash
sudo pip3 install --break-system-packages xlsxwriter
```

### 4. Update Odoo Addons Path (if using custom directory)
Edit your odoo.conf file and add your custom addons path:

```ini
[options]
addons_path = /opt/odoo/addons,/path/to/your/custom_addons
```

### 5. Restart Odoo Service
```bash
sudo systemctl restart odoo
# or
sudo service odoo restart
```

### 6. Update Apps List in Odoo
1. Login to Odoo as Administrator
2. Go to **Settings**
3. Activate **Developer Mode**:
   - Settings → Developer Tools → Activate Developer Mode
4. Go to **Apps**
5. Click the **Update Apps List** button
6. Click **Update** in the confirmation dialog

### 7. Install the Module
1. In the Apps menu, search for: **Enhanced Stock Card**
2. Click **Install** button
3. Wait for installation to complete

### 8. Verify Installation
1. Go to **Inventory** menu
2. Check for **Reporting → Stock Card Report** menu item
3. If visible, installation is successful!

## Configuration Requirements

### Before Using the Module

1. **Enable Anglo-Saxon Accounting**:
   - Settings → Accounting → Configuration
   - Check "Anglo-Saxon Accounting"

2. **Configure Product Costing**:
   - Each product should have:
     - Costing Method: Average Cost (AVCO)
     - Product Type: Storable Product
     - Inventory Valuation: Automated

3. **Configure Locations**:
   - Ensure you have internal locations set up
   - Inventory → Configuration → Locations

## Troubleshooting

### Module Not Appearing in Apps List
- Ensure folder is named exactly `enhanced_stock_card`
- Check addons_path in odoo.conf includes the directory
- Restart Odoo service
- Clear browser cache
- Update Apps List again

### Import Error: xlsxwriter
Install the library:
```bash
pip install xlsxwriter
```

### Permission Denied Errors
Ensure Odoo user has read permissions:
```bash
sudo chown -R odoo:odoo /path/to/enhanced_stock_card
sudo chmod -R 755 /path/to/enhanced_stock_card
```

### Menu Not Showing
- Verify user has "Inventory / User" access rights
- Refresh browser (Ctrl+F5)
- Re-login to Odoo

### Report Shows No Data
- Check that products have type = "Storable Product"
- Verify stock moves exist in the date range
- Ensure costing method is set to AVCO
- Check that inventory valuation is automated

## Module Structure
```
enhanced_stock_card/
├── __init__.py                     # Main module init
├── __manifest__.py                 # Module manifest
├── README.md                       # This file
├── INSTALLATION.md                 # Installation guide
├── models/                         # Python models
│   ├── __init__.py
│   └── stock_card_wizard.py       # Main wizard logic
├── report/                         # Report files
│   ├── __init__.py
│   ├── stock_card_report.py       # Report model
│   └── stock_card_templates.xml   # QWeb templates
├── views/                          # UI views
│   ├── stock_card_wizard_views.xml
│   └── menu_views.xml
├── security/                       # Access rights
│   └── ir.model.access.csv
└── static/                         # Static files
    └── description/
        ├── index.html              # Module description
        └── icon.svg                # Module icon
```

## Support

For issues or questions:
1. Check Odoo logs: `/var/log/odoo/odoo-server.log`
2. Enable debug mode for detailed error messages
3. Contact your system administrator

## Uninstallation

To uninstall:
1. Go to Apps
2. Search for "Enhanced Stock Card"
3. Click Uninstall
4. Confirm uninstallation

To completely remove files:
```bash
sudo rm -rf /path/to/addons/enhanced_stock_card
```

## Next Steps

After installation:
1. Go to Inventory → Reporting → Stock Card Report
2. Select a product
3. Choose date range
4. Click "Print PDF" to test
5. Review the 16-column report

Enjoy your comprehensive stock card reporting!
