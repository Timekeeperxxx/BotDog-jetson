import { useConfig } from '../../hooks/useConfig'
import { ConfigPanel } from '../../components/ConfigPanel'
import { AdminCard } from '../AdminUi'

export function AdminConfigPage({ configHook }: { configHook: ReturnType<typeof useConfig> }) {
  return (
    <AdminCard
      title="配置中心"
      subtitle="集中查看和修改系统参数，保存前会提示生效方式。"
      className="overflow-hidden"
    >
      <div className="-mx-5 -mb-4 -mt-4">
        <ConfigPanel configHook={configHook} />
      </div>
    </AdminCard>
  )
}
