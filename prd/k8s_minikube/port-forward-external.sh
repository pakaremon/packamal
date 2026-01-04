#!/bin/bash
# Port forwarding script for external access
# This sets up kubectl port-forward AND socat to forward from 0.0.0.0 to localhost
# Run this on the VM to enable external access via the VM's public IP

NAMESPACE="packamal"
FLOWER_PORT=5555
FRONTEND_PORT=8080
# Internal ports for kubectl (different from external ports to avoid conflicts)
FLOWER_INTERNAL=15555
FRONTEND_INTERNAL=18080

start_forwarding() {
    echo "Starting port forwarding for external access..."
    echo "Services will be accessible at:"
    echo "  Flower:   http://20.187.145.56:$FLOWER_PORT"
    echo "  Frontend: http://20.187.145.56:$FRONTEND_PORT"
    echo ""
    echo "Note: Make sure Azure NSG allows inbound traffic on ports $FLOWER_PORT and $FRONTEND_PORT"
    echo ""
    
    # Check if socat is installed
    if ! command -v socat &> /dev/null; then
        echo "Installing socat..."
        sudo apt-get update -qq && sudo apt-get install -y socat
    fi
    
    # Kill any existing port-forward and socat processes
    pkill -f "kubectl port-forward.*flower" 2>/dev/null
    pkill -f "kubectl port-forward.*frontend" 2>/dev/null
    pkill -f "socat.*:$FLOWER_PORT" 2>/dev/null
    pkill -f "socat.*:$FRONTEND_PORT" 2>/dev/null
    
    # Start kubectl port-forward to localhost on internal ports
    kubectl port-forward -n $NAMESPACE --address 127.0.0.1 svc/flower $FLOWER_INTERNAL:5555 > /tmp/flower-port-forward.log 2>&1 &
    FLOWER_KUBECTL_PID=$!
    
    kubectl port-forward -n $NAMESPACE --address 127.0.0.1 svc/frontend $FRONTEND_INTERNAL:80 > /tmp/frontend-port-forward.log 2>&1 &
    FRONTEND_KUBECTL_PID=$!
    
    sleep 2
    
    # Start socat to forward from 0.0.0.0 (external) to localhost (internal)
    socat TCP-LISTEN:$FLOWER_PORT,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:$FLOWER_INTERNAL > /tmp/flower-socat.log 2>&1 &
    FLOWER_SOCAT_PID=$!
    
    socat TCP-LISTEN:$FRONTEND_PORT,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:$FRONTEND_INTERNAL > /tmp/frontend-socat.log 2>&1 &
    FRONTEND_SOCAT_PID=$!
    
    sleep 2
    
    # Check if processes are still running
    if ps -p $FLOWER_KUBECTL_PID > /dev/null && ps -p $FRONTEND_KUBECTL_PID > /dev/null && \
       ps -p $FLOWER_SOCAT_PID > /dev/null && ps -p $FRONTEND_SOCAT_PID > /dev/null; then
        echo "Port forwarding started successfully!"
        echo "  Flower kubectl PID: $FLOWER_KUBECTL_PID"
        echo "  Flower socat PID: $FLOWER_SOCAT_PID"
        echo "  Frontend kubectl PID: $FRONTEND_KUBECTL_PID"
        echo "  Frontend socat PID: $FRONTEND_SOCAT_PID"
        echo ""
        echo "Logs:"
        echo "  Flower:   /tmp/flower-port-forward.log, /tmp/flower-socat.log"
        echo "  Frontend: /tmp/frontend-port-forward.log, /tmp/frontend-socat.log"
        echo ""
        echo "To stop, run: $0 stop"
        
        # Save PIDs
        echo "$FLOWER_KUBECTL_PID $FLOWER_SOCAT_PID $FRONTEND_KUBECTL_PID $FRONTEND_SOCAT_PID" > /tmp/packamal-port-forward.pids
    else
        echo "Error: Port forwarding failed to start"
        echo "Check logs for details"
        exit 1
    fi
}

stop_forwarding() {
    echo "Stopping port forwarding..."
    pkill -f "kubectl port-forward.*flower" 2>/dev/null
    pkill -f "kubectl port-forward.*frontend" 2>/dev/null
    pkill -f "socat.*:$FLOWER_PORT" 2>/dev/null
    pkill -f "socat.*:$FRONTEND_PORT" 2>/dev/null
    rm -f /tmp/packamal-port-forward.pids
    echo "Port forwarding stopped"
}

status() {
    if pgrep -f "kubectl port-forward.*flower" > /dev/null && pgrep -f "socat.*:$FLOWER_PORT" > /dev/null; then
        echo "Port forwarding is RUNNING"
        echo "  Flower:   http://20.187.145.56:$FLOWER_PORT"
        echo "  Frontend: http://20.187.145.56:$FRONTEND_PORT"
        echo ""
        echo "Verify with: curl -I http://20.187.145.56:$FLOWER_PORT"
    else
        echo "Port forwarding is NOT running"
        echo "Start it with: $0 start"
    fi
}

case "$1" in
    start)
        start_forwarding
        ;;
    stop)
        stop_forwarding
        ;;
    status)
        status
        ;;
    restart)
        stop_forwarding
        sleep 1
        start_forwarding
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        echo ""
        echo "This script sets up port forwarding so external clients can access:"
        echo "  Flower:   http://20.187.145.56:$FLOWER_PORT"
        echo "  Frontend: http://20.187.145.56:$FRONTEND_PORT"
        exit 1
        ;;
esac
