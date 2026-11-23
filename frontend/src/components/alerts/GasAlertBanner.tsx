import { ExternalLink, TriangleAlert } from 'lucide-react'
import { getApiBaseUrl } from '../../config/api'
import { useGasMonitor } from '../../hooks/useGasMonitor'
import './gasAlertBanner.css'

export function GasAlertBanner() {
  const monitor = useGasMonitor()
  if (monitor.state !== 'unavailable' && monitor.alerts.length === 0) return null

  const critical = monitor.alerts.some((alarm) => alarm.severity === 'CRITICAL')
  const sourceUrl = new URL(getApiBaseUrl())
  sourceUrl.port = '8787'
  sourceUrl.pathname = '/gases'
  sourceUrl.search = ''
  sourceUrl.hash = ''

  return (
    <section className={`gas-alert-banner ${critical ? 'is-critical' : 'is-warning'}`} role="alert" aria-label="气体监测告警">
      <TriangleAlert size={22} aria-hidden="true" />
      <div className="gas-alert-content">
        <strong>{critical ? '气体紧急告警' : monitor.state === 'unavailable' ? '气体监测异常' : '气体告警'}</strong>
        {monitor.state === 'unavailable' ? <span>{monitor.error}</span> : null}
        <ul>
          {monitor.alerts.map((alarm) => (
            <li key={alarm.channel}>
              {monitor.state === 'unavailable' && !alarm.stale ? '上次：' : ''}{alarm.message}
            </li>
          ))}
        </ul>
      </div>
      <a href={sourceUrl.href} target="_blank" rel="noopener noreferrer">查看气体<ExternalLink size={14} aria-hidden="true" /></a>
    </section>
  )
}
