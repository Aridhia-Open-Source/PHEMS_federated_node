#!/bin/bash
# Dagster Database Configuration Validation Script
# This script helps validate that Dagster is properly configured to use an existing database

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="${NAMESPACE:-default}"
RELEASE_NAME="${RELEASE_NAME:-federated-node}"
DB_NAME="${DB_NAME:-dagster_db}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Dagster Database Configuration Validator${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE_NAME"
echo "Dagster DB: $DB_NAME"
echo ""

# Function to check command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}✗ $1 is not installed${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ $1 is installed${NC}"
    return 0
}

# Function to check pod status
check_pod_status() {
    local label=$1
    local expected_count=$2
    
    local count=$(kubectl get pods -n $NAMESPACE -l $label --no-headers 2>/dev/null | wc -l)
    local running=$(kubectl get pods -n $NAMESPACE -l $label --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    
    if [ $count -eq 0 ]; then
        echo -e "${RED}✗ No pods found with label: $label${NC}"
        return 1
    elif [ $running -ne $count ]; then
        echo -e "${YELLOW}⚠ $running/$count pods running for: $label${NC}"
        kubectl get pods -n $NAMESPACE -l $label --no-headers
        return 1
    else
        echo -e "${GREEN}✓ All $count pods running for: $label${NC}"
        return 0
    fi
}

# Function to check database
check_database() {
    local db_pod=$1
    local db_user=$2
    local db_name=$3
    
    echo "Checking database '$db_name' on pod '$db_pod'..."
    
    # Check if database exists
    if kubectl exec -n $NAMESPACE $db_pod -- psql -U $db_user -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw $db_name; then
        echo -e "${GREEN}✓ Database '$db_name' exists${NC}"
        
        # Check for Dagster tables
        local table_count=$(kubectl exec -n $NAMESPACE $db_pod -- psql -U $db_user -d $db_name -tc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null | tr -d ' ')
        
        if [ "$table_count" -gt 0 ]; then
            echo -e "${GREEN}✓ Database has $table_count tables${NC}"
            
            # Check for key Dagster tables
            local dagster_tables=("runs" "event_logs" "jobs" "schedules")
            for table in "${dagster_tables[@]}"; do
                if kubectl exec -n $NAMESPACE $db_pod -- psql -U $db_user -d $db_name -tc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='$table')" 2>/dev/null | grep -q t; then
                    echo -e "${GREEN}  ✓ Table '$table' exists${NC}"
                else
                    echo -e "${YELLOW}  ⚠ Table '$table' not found (may need migration)${NC}"
                fi
            done
        else
            echo -e "${YELLOW}⚠ Database is empty (run migration)${NC}"
        fi
        return 0
    else
        echo -e "${RED}✗ Database '$db_name' does not exist${NC}"
        return 1
    fi
}

echo -e "${BLUE}Step 1: Checking prerequisites${NC}"
echo "---"
check_command kubectl || exit 1
check_command helm || exit 1
echo ""

echo -e "${BLUE}Step 2: Checking Helm release${NC}"
echo "---"
if helm list -n $NAMESPACE | grep -q $RELEASE_NAME; then
    echo -e "${GREEN}✓ Helm release '$RELEASE_NAME' found${NC}"
    helm list -n $NAMESPACE | grep $RELEASE_NAME
else
    echo -e "${RED}✗ Helm release '$RELEASE_NAME' not found${NC}"
    exit 1
fi
echo ""

echo -e "${BLUE}Step 3: Checking Dagster pods${NC}"
echo "---"
check_pod_status "app.kubernetes.io/component=dagster-webserver" 1
check_pod_status "app.kubernetes.io/component=dagster-daemon" 1
check_pod_status "app.kubernetes.io/instance=$RELEASE_NAME" 0  # Any Dagster pod
echo ""

echo -e "${BLUE}Step 4: Checking for PostgreSQL subchart (should NOT exist)${NC}"
echo "---"
if kubectl get statefulset -n $NAMESPACE | grep -q "postgresql"; then
    echo -e "${RED}✗ Found PostgreSQL StatefulSet (should be disabled!)${NC}"
    kubectl get statefulset -n $NAMESPACE | grep postgresql
else
    echo -e "${GREEN}✓ No PostgreSQL subchart deployed (good!)${NC}"
fi
echo ""

echo -e "${BLUE}Step 5: Checking ConfigMap${NC}"
echo "---"
if kubectl get configmap -n $NAMESPACE dagster-env-config &>/dev/null; then
    echo -e "${GREEN}✓ ConfigMap 'dagster-env-config' exists${NC}"
    echo "Environment variables:"
    kubectl get configmap -n $NAMESPACE dagster-env-config -o jsonpath='{.data}' | jq '.' 2>/dev/null || kubectl get configmap -n $NAMESPACE dagster-env-config -o yaml | grep -A 20 "data:"
else
    echo -e "${YELLOW}⚠ ConfigMap 'dagster-env-config' not found${NC}"
fi
echo ""

echo -e "${BLUE}Step 6: Checking database secret${NC}"
echo "---"
if kubectl get secret -n $NAMESPACE backend-secrets &>/dev/null; then
    echo -e "${GREEN}✓ Secret 'backend-secrets' exists${NC}"
    echo "Keys in secret:"
    kubectl get secret -n $NAMESPACE backend-secrets -o jsonpath='{.data}' | jq 'keys' 2>/dev/null || echo "(jq not available)"
else
    echo -e "${RED}✗ Secret 'backend-secrets' not found${NC}"
fi
echo ""

echo -e "${BLUE}Step 7: Checking Dagster webserver logs${NC}"
echo "---"
WEBSERVER_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=dagster-webserver -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -n "$WEBSERVER_POD" ]; then
    echo "Webserver pod: $WEBSERVER_POD"
    echo "Recent logs:"
    kubectl logs -n $NAMESPACE $WEBSERVER_POD --tail=20 2>/dev/null || echo -e "${YELLOW}⚠ Could not fetch logs${NC}"
    
    # Check for database connection messages
    if kubectl logs -n $NAMESPACE $WEBSERVER_POD --tail=100 2>/dev/null | grep -qi "database"; then
        echo ""
        echo "Database-related log entries:"
        kubectl logs -n $NAMESPACE $WEBSERVER_POD --tail=100 2>/dev/null | grep -i "database" | tail -5
    fi
else
    echo -e "${YELLOW}⚠ Webserver pod not found${NC}"
fi
echo ""

echo -e "${BLUE}Step 8: Checking database${NC}"
echo "---"
# Try to find the PostgreSQL pod
DB_POD=$(kubectl get pods -n $NAMESPACE | grep -E "postgres|mariadb|mysql" | grep -v dagster | awk '{print $1}' | head -1)

if [ -n "$DB_POD" ]; then
    echo "Database pod: $DB_POD"
    
    # Get database user from ConfigMap
    DB_USER=$(kubectl get configmap -n $NAMESPACE dagster-env-config -o jsonpath='{.data.DAGSTER_POSTGRES_USER}' 2>/dev/null || echo "test")
    
    echo "Database user: $DB_USER"
    
    check_database $DB_POD $DB_USER $DB_NAME
else
    echo -e "${YELLOW}⚠ Could not find database pod${NC}"
    echo "Available pods:"
    kubectl get pods -n $NAMESPACE
fi
echo ""

echo -e "${BLUE}Step 9: Testing Dagster API${NC}"
echo "---"
if [ -n "$WEBSERVER_POD" ]; then
    echo "Testing /server_info endpoint..."
    if kubectl exec -n $NAMESPACE $WEBSERVER_POD -- wget -q -O- http://localhost:3000/server_info 2>/dev/null | head -20; then
        echo -e "${GREEN}✓ Dagster webserver API responding${NC}"
    else
        echo -e "${YELLOW}⚠ Could not reach webserver API${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Skipping (webserver pod not found)${NC}"
fi
echo ""

echo -e "${BLUE}Step 10: Summary${NC}"
echo "---"

# Count successes and failures
DAEMON_POD=$(kubectl get pods -n $NAMESPACE -l app.kubernetes.io/component=dagster-daemon -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

CHECKS_PASSED=0
CHECKS_TOTAL=6

# Check 1: Pods running
if [ -n "$WEBSERVER_POD" ] && [ -n "$DAEMON_POD" ]; then
    ((CHECKS_PASSED++))
    echo -e "${GREEN}✓ Dagster pods are running${NC}"
else
    echo -e "${RED}✗ Dagster pods are not running${NC}"
fi

# Check 2: No PostgreSQL subchart
if ! kubectl get statefulset -n $NAMESPACE 2>/dev/null | grep -q "postgresql"; then
    ((CHECKS_PASSED++))
    echo -e "${GREEN}✓ PostgreSQL subchart is disabled${NC}"
else
    echo -e "${RED}✗ PostgreSQL subchart is still deployed${NC}"
fi

# Check 3: ConfigMap exists
if kubectl get configmap -n $NAMESPACE dagster-env-config &>/dev/null; then
    ((CHECKS_PASSED++))
    echo -e "${GREEN}✓ Environment ConfigMap exists${NC}"
else
    echo -e "${RED}✗ Environment ConfigMap missing${NC}"
fi

# Check 4: Secret exists
if kubectl get secret -n $NAMESPACE backend-secrets &>/dev/null; then
    ((CHECKS_PASSED++))
    echo -e "${GREEN}✓ Database secret exists${NC}"
else
    echo -e "${RED}✗ Database secret missing${NC}"
fi

# Check 5: Database exists
if [ -n "$DB_POD" ]; then
    DB_USER=$(kubectl get configmap -n $NAMESPACE dagster-env-config -o jsonpath='{.data.DAGSTER_POSTGRES_USER}' 2>/dev/null || echo "test")
    if kubectl exec -n $NAMESPACE $DB_POD -- psql -U $DB_USER -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw $DB_NAME; then
        ((CHECKS_PASSED++))
        echo -e "${GREEN}✓ Dagster database exists${NC}"
    else
        echo -e "${RED}✗ Dagster database not found${NC}"
        echo -e "${YELLOW}  Run: kubectl exec -n $NAMESPACE $DB_POD -- psql -U $DB_USER -c 'CREATE DATABASE $DB_NAME;'${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Could not verify database (pod not found)${NC}"
fi

# Check 6: Webserver responding
if [ -n "$WEBSERVER_POD" ]; then
    if kubectl exec -n $NAMESPACE $WEBSERVER_POD -- wget -q -O- http://localhost:3000/server_info &>/dev/null; then
        ((CHECKS_PASSED++))
        echo -e "${GREEN}✓ Dagster webserver is responding${NC}"
    else
        echo -e "${RED}✗ Dagster webserver not responding${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Could not test webserver (pod not found)${NC}"
fi

echo ""
echo -e "${BLUE}Results: $CHECKS_PASSED/$CHECKS_TOTAL checks passed${NC}"

if [ $CHECKS_PASSED -eq $CHECKS_TOTAL ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo -e "${GREEN}Dagster is properly configured to use${NC}"
    echo -e "${GREEN}the existing database.${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Access Dagster UI:"
    echo "   kubectl port-forward -n $NAMESPACE svc/${RELEASE_NAME}-dagster-webserver 8080:80"
    echo "   Open: http://localhost:8080"
    echo ""
    echo "2. Run a test job in the Dagster UI"
    echo ""
    exit 0
else
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}⚠ Some checks failed${NC}"
    echo -e "${YELLOW}Review the output above for details${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    echo "Common fixes:"
    echo "1. Create Dagster database:"
    echo "   kubectl exec -n $NAMESPACE $DB_POD -- psql -U <user> -c 'CREATE DATABASE $DB_NAME;'"
    echo ""
    echo "2. Run Dagster migrations:"
    echo "   kubectl exec -n $NAMESPACE $WEBSERVER_POD -- dagster instance migrate"
    echo ""
    echo "3. Check pod logs:"
    echo "   kubectl logs -n $NAMESPACE $WEBSERVER_POD"
    echo ""
    exit 1
fi
