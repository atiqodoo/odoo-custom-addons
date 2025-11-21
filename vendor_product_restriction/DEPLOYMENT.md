# Production Deployment Checklist

## Pre-Deployment (1 Week Before)

### Environment Preparation

- [ ] **Backup Production Database**
  ```bash
  pg_dump -U odoo -F c production_db > backup_$(date +%Y%m%d).dump
  ```

- [ ] **Test in Staging Environment**
  - [ ] Install module in staging
  - [ ] Run full test suite (TESTING.md)
  - [ ] Verify integration with existing modules
  - [ ] Performance testing with production data volume

- [ ] **Document Current State**
  - [ ] List all existing custom modules
  - [ ] Document current purchase workflow
  - [ ] Screenshot current RFQ creation process
  - [ ] Export current user permissions

### Data Preparation

- [ ] **Audit Vendor-Product Mappings**
  ```sql
  SELECT 
    COUNT(*) as total_products,
    COUNT(CASE WHEN supplier_count > 0 THEN 1 END) as products_with_vendors,
    COUNT(CASE WHEN supplier_count = 0 THEN 1 END) as products_without_vendors
  FROM (
    SELECT 
      pt.id,
      COUNT(ps.id) as supplier_count
    FROM product_template pt
    LEFT JOIN product_supplierinfo ps ON ps.product_tmpl_id = pt.id
    WHERE pt.purchase_ok = TRUE
    GROUP BY pt.id
  ) as summary;
  ```

- [ ] **Identify Unmapped Products**
  ```sql
  SELECT 
    pt.id,
    pt.name,
    pt.default_code
  FROM product_template pt
  WHERE pt.purchase_ok = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM product_supplierinfo ps 
    WHERE ps.product_tmpl_id = pt.id
  )
  ORDER BY pt.name;
  ```

- [ ] **Clean Up Inactive Mappings**
  ```sql
  UPDATE product_supplierinfo
  SET active = FALSE
  WHERE partner_id IN (
    SELECT id FROM res_partner 
    WHERE active = FALSE OR supplier_rank = 0
  );
  ```

- [ ] **Bulk Import Missing Mappings** (if needed)
  - [ ] Export template CSV
  - [ ] Fill in vendor data
  - [ ] Import via Odoo import tool
  - [ ] Verify import success

### User Preparation

- [ ] **Identify User Groups**
  ```
  Override Users (Unrestricted):
  - [ ] Purchase Managers: _____
  - [ ] Administrators: _____
  - [ ] Special Cases: _____
  
  Restricted Users:
  - [ ] Purchase Users: _____
  - [ ] Buyer Team: _____
  - [ ] Other: _____
  ```

- [ ] **Create User Communication**
  - [ ] Email announcement (draft)
  - [ ] Training session scheduled
  - [ ] Quick reference guide prepared
  - [ ] FAQ document ready

---

## Deployment Day

### Step 1: Final Backup (T-0)

- [ ] **Stop Odoo Service**
  ```bash
  sudo systemctl stop odoo
  ```

- [ ] **Create Final Backup**
  ```bash
  pg_dump -U odoo -F c production_db > final_backup_$(date +%Y%m%d_%H%M).dump
  ```

- [ ] **Backup Filestore**
  ```bash
  tar -czf filestore_backup_$(date +%Y%m%d_%H%M).tar.gz /opt/odoo/data/filestore
  ```

### Step 2: Module Installation (T+15 min)

- [ ] **Copy Module to Addons**
  ```bash
  cp -r vendor_product_restriction /opt/odoo/custom-addons/
  chown -R odoo:odoo /opt/odoo/custom-addons/vendor_product_restriction
  chmod -R 755 /opt/odoo/custom-addons/vendor_product_restriction
  ```

- [ ] **Update Apps List**
  ```bash
  sudo -u odoo /opt/odoo/odoo-bin -d production_db --update=all --stop-after-init
  ```

- [ ] **Install Module**
  ```bash
  sudo -u odoo /opt/odoo/odoo-bin -d production_db -i vendor_product_restriction --stop-after-init
  ```

- [ ] **Check Logs for Errors**
  ```bash
  tail -n 100 /var/log/odoo/odoo-server.log
  ```

### Step 3: Verify Installation (T+30 min)

- [ ] **Start Odoo Service**
  ```bash
  sudo systemctl start odoo
  ```

- [ ] **Database Check**
  ```sql
  -- Verify security group created
  SELECT id, name FROM res_groups 
  WHERE name LIKE '%Vendor Restriction%';
  
  -- Verify admin has override
  SELECT u.login, g.name 
  FROM res_users u
  JOIN res_groups_users_rel r ON r.uid = u.id
  JOIN res_groups g ON g.id = r.gid
  WHERE g.name LIKE '%Vendor Restriction%';
  ```

- [ ] **UI Verification**
  - [ ] Login as administrator
  - [ ] Navigate to Purchase → Orders → Create
  - [ ] Verify green "Override Active" badge appears
  - [ ] Verify all products visible in dropdown

- [ ] **Smoke Test**
  - [ ] Create test RFQ as admin
  - [ ] Add 2 products
  - [ ] Save as draft
  - [ ] Confirm RFQ
  - [ ] Verify no errors

### Step 4: User Permission Setup (T+45 min)

- [ ] **Grant Override to Managers**
  ```
  For each Purchase Manager:
  1. Settings → Users → [Select User]
  2. Access Rights → Purchase section
  3. Enable: "Purchase: Vendor Restriction Override"
  4. Save
  ```

- [ ] **Verify Restricted Users**
  ```
  For sample Purchase User:
  1. Settings → Users → [Select User]
  2. Access Rights → Purchase section
  3. Verify: "Purchase: Vendor Restriction Override" is UNCHECKED
  4. Save
  ```

- [ ] **Test with Real Users**
  - [ ] Login as restricted user
  - [ ] Create RFQ with vendor
  - [ ] Verify product filtering works
  - [ ] Test warning message display

---

## Post-Deployment (Same Day)

### Immediate Verification (T+1 hour)

- [ ] **Monitor Server Performance**
  ```bash
  # CPU and Memory
  top -u odoo
  
  # Active connections
  psql -U postgres -c "SELECT count(*) FROM pg_stat_activity WHERE datname='production_db';"
  
  # Slow queries
  tail -f /var/log/odoo/odoo-server.log | grep "SLOW QUERY"
  ```

- [ ] **Check Error Logs**
  ```bash
  # Filter for new errors
  grep -i "error\|exception\|traceback" /var/log/odoo/odoo-server.log | tail -n 50
  ```

- [ ] **User Feedback Collection**
  - [ ] Send initial feedback survey
  - [ ] Monitor support tickets
  - [ ] Check internal chat for issues

### Functional Testing (T+2 hours)

- [ ] **Run Priority Test Cases**
  - [ ] TC1.1: Restricted user basic filtering
  - [ ] TC1.3: Unmapped product warning
  - [ ] TC3.1: Override user sees all products
  - [ ] TC5.1: Integration with custom pricing
  - [ ] TC5.2: Integration with vendor bill wizard

- [ ] **Real Transaction Test**
  - [ ] Create actual RFQ with real vendor
  - [ ] Follow through complete workflow:
    1. RFQ creation with filtered products
    2. Send to vendor for approval
    3. Confirm RFQ → PO
    4. Create vendor bill
    5. Process payment
  - [ ] Verify no interruptions

### Communication (T+3 hours)

- [ ] **Send Success Notification**
  ```
  To: All Purchase Users
  Subject: New Vendor Product Filtering Now Active
  
  The vendor product restriction module has been successfully 
  deployed. You will now see products filtered based on your 
  selected vendor when creating RFQs.
  
  Key Points:
  - Select vendor first, then add products
  - Only products mapped to vendor will appear
  - Warning messages guide you if product unavailable
  - Contact IT if you need unrestricted access
  
  Training session: [Date/Time]
  Documentation: [Link]
  Support: [Contact]
  ```

- [ ] **Update Internal Documentation**
  - [ ] Add to purchase workflow guide
  - [ ] Update user training materials
  - [ ] Document in IT knowledge base

---

## Day 2-7: Monitoring Period

### Daily Checks

- [ ] **Day 2**: Monitor usage patterns
  - [ ] Review server logs
  - [ ] Check support tickets
  - [ ] Collect user feedback
  - [ ] Performance metrics

- [ ] **Day 3**: Analyze warnings
  ```sql
  -- Identify most common unmapped products
  -- (requires custom logging if implemented)
  ```
  - [ ] Review which products trigger warnings
  - [ ] Plan vendor mapping updates

- [ ] **Day 4**: User adoption
  - [ ] Survey completion rate
  - [ ] Training session attendance
  - [ ] Support ticket volume

- [ ] **Day 5**: Performance review
  - [ ] Query performance acceptable?
  - [ ] Any slowdowns reported?
  - [ ] Server resources adequate?

- [ ] **Day 6**: Integration check
  - [ ] Custom pricing working?
  - [ ] Vendor bill wizard working?
  - [ ] Any workflow disruptions?

- [ ] **Day 7**: Weekly review
  - [ ] Total RFQs created
  - [ ] Warnings triggered
  - [ ] Support tickets resolved
  - [ ] User satisfaction score

### Issue Tracking

```
Issue Log:
┌──────┬──────────┬──────────┬──────────┬──────────┐
│ ID   │ Date     │ Severity │ Issue    │ Status   │
├──────┼──────────┼──────────┼──────────┼──────────┤
│ 001  │          │          │          │          │
│ 002  │          │          │          │          │
│ 003  │          │          │          │          │
└──────┴──────────┴──────────┴──────────┴──────────┘
```

---

## Week 2-4: Optimization Period

### Week 2 Tasks

- [ ] **Analyze Warning Patterns**
  - [ ] Identify most-requested unmapped products
  - [ ] Create vendor mapping batch
  - [ ] Import new mappings

- [ ] **User Training Follow-up**
  - [ ] Schedule additional sessions for questions
  - [ ] Update FAQ based on support tickets
  - [ ] Create video tutorials

- [ ] **Performance Optimization**
  - [ ] Add database indexes if needed
  - [ ] Optimize slow queries
  - [ ] Review caching strategy

### Week 3 Tasks

- [ ] **Feature Refinement**
  - [ ] Collect enhancement requests
  - [ ] Prioritize improvements
  - [ ] Plan module updates

- [ ] **Documentation Updates**
  - [ ] Address gaps in documentation
  - [ ] Add real-world examples
  - [ ] Update troubleshooting guide

### Week 4 Tasks

- [ ] **Final Review Meeting**
  - [ ] Deployment success metrics
  - [ ] User adoption rate
  - [ ] Performance impact
  - [ ] Next steps

- [ ] **Sign-off**
  - [ ] Project manager approval
  - [ ] Stakeholder satisfaction
  - [ ] Move to BAU support

---

## Rollback Procedure (If Needed)

### Emergency Rollback

**Trigger Criteria:**
- Critical production errors
- Data corruption
- Workflow blocking issues
- >50% user complaints

**Steps:**

1. [ ] **Stop Odoo Immediately**
   ```bash
   sudo systemctl stop odoo
   ```

2. [ ] **Uninstall Module**
   ```bash
   sudo -u odoo /opt/odoo/odoo-bin -d production_db -u vendor_product_restriction --stop-after-init
   # Then manually uninstall via UI after starting
   ```

3. [ ] **Restore Backup if Data Issues**
   ```bash
   sudo -u postgres dropdb production_db
   sudo -u postgres pg_restore -C -d postgres final_backup_TIMESTAMP.dump
   ```

4. [ ] **Restart Odoo**
   ```bash
   sudo systemctl start odoo
   ```

5. [ ] **Verify System Stability**
   - [ ] Test RFQ creation
   - [ ] Verify no errors
   - [ ] Check user access

6. [ ] **Communicate Rollback**
   - [ ] Notify all users
   - [ ] Explain situation
   - [ ] Provide timeline for fix

---

## Success Criteria

### Technical Metrics

- [ ] Zero critical errors in production
- [ ] <5 support tickets in first week
- [ ] <2 second product dropdown load time
- [ ] No performance degradation
- [ ] 100% data integrity maintained

### Business Metrics

- [ ] >90% user adoption rate
- [ ] <10% users requesting override access
- [ ] Reduction in wrong-vendor purchases
- [ ] Improved vendor relationship compliance
- [ ] Positive user feedback (>70% satisfaction)

### Operational Metrics

- [ ] Training completed for all users
- [ ] Documentation accessed by >50% users
- [ ] Support response time <2 hours
- [ ] Issue resolution time <1 day
- [ ] Zero rollbacks required

---

## Sign-off

### Pre-Deployment Approval

- [ ] **Technical Lead:** ________________ Date: ________
- [ ] **QA Manager:** ________________ Date: ________
- [ ] **Purchase Manager:** ________________ Date: ________
- [ ] **IT Director:** ________________ Date: ________

### Post-Deployment Approval

- [ ] **Week 1 Review:** ________________ Date: ________
- [ ] **Week 4 Sign-off:** ________________ Date: ________
- [ ] **Final Approval:** ________________ Date: ________

---

## Lessons Learned

Document key learnings for future deployments:

```
What Went Well:
- 
- 
- 

What Could Be Improved:
- 
- 
- 

Recommendations for Next Time:
- 
- 
- 
```

---

## Support Contacts

**During Deployment:**
- Primary: ________________ (Mobile: ___________)
- Backup: ________________ (Mobile: ___________)
- On-Call: ________________ (24/7: ___________)

**Post-Deployment:**
- Technical Support: support@yourcompany.com
- Purchase Team Lead: purchase.manager@yourcompany.com
- IT Helpdesk: (555) 123-4567
