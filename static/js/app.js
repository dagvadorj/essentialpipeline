/**
 * EssentialPipeline Pipeline Tool - Main JavaScript
 */

// Initialize Bootstrap tooltips
const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl)
})

// Initialize Bootstrap popovers
const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl)
})

// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert[data-auto-dismiss]')
    
    alerts.forEach(function(alert) {
        const timeout = parseInt(alert.getAttribute('data-auto-dismiss')) || 5000
        
        setTimeout(function() {
            const bsAlert = bootstrap.Alert.getInstance(alert)
            if (bsAlert) {
                bsAlert.close()
            }
        }, timeout)
    })
})

// HTMX configuration
document.addEventListener('DOMContentLoaded', function() {
    // Configure HTMX to use Bootstrap alerts for error messages
    htmx.onLoad(function(content) {
        // Add loading indicators to forms
        const forms = content.querySelectorAll('form[hx-post], form[hx-put], form[hx-patch], form[hx-delete]')
        forms.forEach(function(form) {
            form.addEventListener('htmx:beforeRequest', function(evt) {
                const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]')
                if (submitBtn) {
                    submitBtn.disabled = true
                    const originalText = submitBtn.innerHTML
                    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...'
                    submitBtn.setAttribute('data-original-text', originalText)
                }
            })
            
            form.addEventListener('htmx:afterRequest', function(evt) {
                const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]')
                if (submitBtn) {
                    submitBtn.disabled = false
                    const originalText = submitBtn.getAttribute('data-original-text')
                    if (originalText) {
                        submitBtn.innerHTML = originalText
                        submitBtn.removeAttribute('data-original-text')
                    }
                }
            })
        })
    })
    
    // Configure HTMX to show server errors in alerts
    htmx.on('htmx:responseError', function(evt) {
        const errorMsg = `Error: ${evt.detail.xhr.status} - ${evt.detail.xhr.responseText || 'Server Error'}`
        showAlert('Error', errorMsg, 'danger')
    })
})

// Show alert function
function showAlert(title, message, type = 'info') {
    const alertContainer = document.querySelector('.alert-container') || document.body
    const alertId = 'alert-' + Date.now()
    
    const alertHtml = `
        <div id="${alertId}" class="alert alert-${type} alert-dismissible fade show" role="alert">
            <strong>${title}:</strong> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `
    
    alertContainer.insertAdjacentHTML('afterbegin', alertHtml)
    
    // Auto-dismiss after 5 seconds
    setTimeout(function() {
        const alert = document.getElementById(alertId)
        if (alert) {
            bootstrap.Alert.getInstance(alert).close()
        }
    }, 5000)
}

// Utility functions
function formatDate(dateString) {
    const date = new Date(dateString)
    return date.toLocaleString()
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// Form utilities
function validateForm(formId) {
    const form = document.getElementById(formId)
    if (!form) return false
    return form.checkValidity()
}

// Confirmation dialogs
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback()
    }
}

// Export for use in other scripts
window.EssentialPipeline = {
    showAlert,
    formatDate,
    formatBytes,
    validateForm,
    confirmAction
}

// Log viewer enhancements
document.addEventListener('DOMContentLoaded', function() {
    const logViewers = document.querySelectorAll('.log-viewer')
    logViewers.forEach(function(viewer) {
        // Auto-scroll to bottom
        const shouldAutoScroll = viewer.hasAttribute('data-auto-scroll')
        if (shouldAutoScroll) {
            viewer.scrollTop = viewer.scrollHeight
        }
    })
})

// Server-Sent Events (SSE) handler for real-time logs
function setupSSE(url, targetElementId) {
    const target = document.getElementById(targetElementId)
    if (!target) return null
    
    const eventSource = new EventSource(url)
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data)
            // Create new log line element
            const logLine = document.createElement('div')
            logLine.className = `log-line level-${data.level || 'info'}`
            logLine.innerHTML = `
                <span class="timestamp text-muted">${formatDate(data.timestamp)}</span>
                <span class="level-badge badge bg-${data.level || 'info'} ms-2">${(data.level || 'info').toUpperCase()}</span>
                <span class="message ms-2">${data.message || ''}</span>
            `
            target.appendChild(logLine)
            target.scrollTop = target.scrollHeight
        } catch (e) {
            console.error('Error parsing SSE message:', e)
        }
    }
    
    eventSource.onerror = function(error) {
        console.error('SSE error:', error)
        eventSource.close()
    }
    
    return eventSource
}

// Auto-refresh for dashboard stats
function setupAutoRefresh(url, elements) {
    function refresh() {
        fetch(url, {
            headers: {
                'Accept': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            elements.forEach(element => {
                const { selector, key } = element
                const el = document.querySelector(selector)
                if (el && data[key] !== undefined) {
                    el.textContent = data[key]
                }
            })
        })
        .catch(error => {
            console.error('Auto-refresh error:', error)
        })
    }
    
    // Refresh immediately
    refresh()
    
    // Then every 30 seconds
    const intervalId = setInterval(refresh, 30000)
    
    return () => clearInterval(intervalId)
}

// Close SSE connections when leaving page
window.addEventListener('beforeunload', function() {
    if (window._sseConnections) {
        window._sseConnections.forEach(conn => conn.close())
    }
})
