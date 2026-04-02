# Dagster External Database Setup - Documentation Index

This directory contains comprehensive documentation for configuring Dagster to use your existing PHEMS Federated Node PostgreSQL database instead of deploying its own database instance.

## 📚 Documentation Overview

### 1. **[DAGSTER_DATABASE_SETUP.md](./DAGSTER_DATABASE_SETUP.md)** - Complete Setup Guide
**Use this for:** Initial setup and detailed explanations

**Contents:**
- Architecture overview and design decisions
- Prerequisites and requirements
- Step-by-step configuration instructions
- Detailed deployment procedures
- Comprehensive validation steps
- Troubleshooting guide
- Production considerations
- Rollback procedures

**Best for:** First-time setup, understanding the architecture, troubleshooting complex issues

---

### 2. **[DAGSTER_SETUP_CHECKLIST.md](./DAGSTER_SETUP_CHECKLIST.md)** - Interactive Checklist
**Use this during:** Deployment and validation

**Contents:**
- Pre-deployment checklist
- Deployment checklist
- Post-deployment validation checklist
- Production readiness checklist
- Rollback checklist
- Common issues reference
- Sign-off section

**Best for:** Ensuring nothing is missed during setup, validation, and production deployment

---

### 3. **[DAGSTER_QUICK_REFERENCE.md](./DAGSTER_QUICK_REFERENCE.md)** - Daily Operations
**Use this for:** Day-to-day management

**Contents:**
- Quick health checks
- Common commands (logs, database, restarts)
- Troubleshooting quick fixes
- Maintenance tasks
- Monitoring commands
- Emergency procedures

**Best for:** Daily operations, quick troubleshooting, common administrative tasks

---

### 4. **[dagster-external-db-example.yaml](./k8s/federated-node/dagster-external-db-example.yaml)** - Configuration Example
**Use this for:** Reference during configuration

**Contents:**
- Example values.yaml configuration
- Annotated with comments explaining each change
- Side-by-side comparison of what to change

**Best for:** Understanding exactly what needs to change in your values.yaml

---

### 5. **[validate_dagster_db.sh](./scripts/validate_dagster_db.sh)** - Validation Script
**Use this for:** Automated validation

**Contents:**
- Automated checks for proper configuration
- Database connectivity tests
- Pod status verification
- Log analysis
- Colored output with actionable results

**Usage:**
```bash
chmod +x scripts/validate_dagster_db.sh
NAMESPACE=<your-namespace> ./scripts/validate_dagster_db.sh
```

**Best for:** Quick validation after deployment or changes

---

## 🚀 Quick Start Path

### For First-Time Setup:

1. **Read** → `DAGSTER_DATABASE_SETUP.md` (sections 1-3)
2. **Reference** → `dagster-external-db-example.yaml`
3. **Follow** → `DAGSTER_SETUP_CHECKLIST.md`
4. **Validate** → Run `validate_dagster_db.sh`
5. **Keep Handy** → `DAGSTER_QUICK_REFERENCE.md`

### For Users:

1. **Operations** → `DAGSTER_QUICK_REFERENCE.md`
2. **Issues** → `DAGSTER_DATABASE_SETUP.md` (Troubleshooting section)
3. **Validation** → Run `validate_dagster_db.sh`

### For Production Deployment:

1. **Plan** → `DAGSTER_DATABASE_SETUP.md` (all sections)
2. **Execute** → `DAGSTER_SETUP_CHECKLIST.md` (all checklists)
3. **Document** → Fill in checklist sign-offs
4. **Monitor** → Use commands from `DAGSTER_QUICK_REFERENCE.md`

---

## 🎯 Use Case Matrix

| **Task** | **Primary Document** | **Supporting Documents** |
|----------|---------------------|--------------------------|
| Initial configuration | Setup Guide | Example Config, Checklist |
| During deployment | Setup Checklist | Setup Guide |
| Validation | Validation Script | Setup Guide, Quick Ref |
| Daily operations | Quick Reference | - |
| Troubleshooting | Setup Guide (Troubleshooting) | Quick Reference |
| Production prep | Setup Guide (Production) | Setup Checklist |
| Team training | All documents | - |
| Emergency issues | Quick Reference (Emergency) | Setup Guide |

---

## 📋 Key Configuration Changes Summary

### What Changes:
1. **Disable** Dagster's PostgreSQL subchart
2. **Configure** connection to existing PostgreSQL
3. **Create** separate `dagster_db` database
4. **Add** ConfigMap for environment variables
5. **Reference** existing secrets for passwords

### What Stays the Same:
- Existing Federated Node database (`fndb`)
- Backend secrets
- PostgreSQL service/pod
- Network configuration

### Benefits:
- ✅ Single PostgreSQL instance for the entire stack
- ✅ Easier resource management
- ✅ Simplified backup procedures
- ✅ Better visibility into database operations
- ✅ Cost savings (fewer pods/resources)

---

## 🔧 Files Created/Modified

### New Files:
```
DAGSTER_DATABASE_SETUP.md                        # Complete guide
DAGSTER_SETUP_CHECKLIST.md                       # Interactive checklist
DAGSTER_QUICK_REFERENCE.md                       # Operations reference
k8s/federated-node/dagster-external-db-example.yaml  # Config example
k8s/federated-node/templates/dagster-env-configmap.yaml  # ConfigMap template
scripts/validate_dagster_db.sh                   # Validation script
```

### Modified Files:
```
k8s/federated-node/values.yaml                   # Main config (to be updated by user)
```

---

## ⚠️ Important Notes

### Before Starting:
1. **Backup your data** - Always have a backup before major changes
2. **Test in development first** - Don't start with production
3. **Review all documents** - Understand what you're changing
4. **Check Kubernetes version** - Ensure compatibility
5. **Verify database version** - PostgreSQL 12+ recommended

### During Deployment:
1. **Monitor logs** - Watch for errors during startup
2. **Validate each step** - Use the checklist
3. **Don't skip validation** - Run the validation script
4. **Document issues** - Note any problems for troubleshooting

### After Deployment:
1. **Test thoroughly** - Run test jobs in Dagster
2. **Monitor resources** - Check CPU/memory usage
3. **Set up monitoring** - Configure alerts
4. **Document configuration** - Keep records of your setup
5. **Train team** - Ensure team knows the new setup

---

## 🆘 Getting Help

### If Something Goes Wrong:

1. **Run validation script:**
   ```bash
   ./scripts/validate_dagster_db.sh
   ```

2. **Check logs:**
   ```bash
   kubectl logs -n <namespace> deployment/<release>-dagster-webserver --tail=100
   kubectl logs -n <namespace> deployment/<release>-dagster-daemon --tail=100
   ```

3. **Review troubleshooting section:**
   - `DAGSTER_DATABASE_SETUP.md` → Troubleshooting section
   - `DAGSTER_QUICK_REFERENCE.md` → Quick Fixes section

4. **Common issues:**
   - CrashLoopBackOff → Check database connectivity
   - Database errors → Verify `dagster_db` exists
   - Permission errors → Check database user privileges
   - Connection refused → Verify service name and port

5. **Rollback if needed:**
   - Follow rollback procedure in `DAGSTER_DATABASE_SETUP.md`
   - Use checklist rollback section

---

## 📊 Success Metrics

Your setup is successful when:

- ✅ All Dagster pods are Running
- ✅ No Dagster PostgreSQL pod exists
- ✅ Dagster UI is accessible
- ✅ Test jobs execute successfully
- ✅ `dagster_db` has Dagster tables
- ✅ `fndb` remains unchanged
- ✅ No connection errors in logs
- ✅ Validation script passes all checks

---

## 🔄 Maintenance

### Regular Tasks:
- **Daily:** Monitor pod status and logs
- **Weekly:** Check database size and performance
- **Monthly:** Review and clean old run data
- **Quarterly:** Review resource usage and scaling needs

### Use:**
- `DAGSTER_QUICK_REFERENCE.md` for maintenance commands
- Validation script for periodic health checks

---

## 📞 Support Resources

### Internal:
- This documentation set
- Validation script output
- Kubernetes/Helm logs

### External:
- [Dagster Documentation](https://docs.dagster.io/)
- [Dagster Helm Chart](https://github.com/dagster-io/dagster/tree/master/helm/dagster)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)

---

## 📝 Feedback

If you find issues with this documentation or have suggestions:

1. Note specific problems in the setup checklist
2. Document workarounds you discover
3. Update this documentation for future users
4. Share knowledge with your team

---

## 🎓 Learning Path

### Beginner:
1. Read Setup Guide introduction and architecture
2. Follow setup checklist step-by-step
3. Use validation script
4. Learn Quick Reference commands

### Intermediate:
1. Understand all configuration options
2. Customize for your environment
3. Implement monitoring
4. Handle common issues independently

### Advanced:
1. Optimize database performance
2. Implement custom configurations
3. Automate deployment and validation
4. Troubleshoot complex issues

---

**Version:** 1.0  
**Last Updated:** April 2026  
**Maintained By:** PHEMS Team

---

## Quick Links

- 📖 [Complete Setup Guide](./DAGSTER_DATABASE_SETUP.md)
- ✅ [Setup Checklist](./DAGSTER_SETUP_CHECKLIST.md)
- 🔧 [Quick Reference](./DAGSTER_QUICK_REFERENCE.md)
- 📄 [Example Config](./k8s/federated-node/dagster-external-db-example.yaml)
- 🔍 [Validation Script](./scripts/validate_dagster_db.sh)
