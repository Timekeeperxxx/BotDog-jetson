import { useConfig } from '../../hooks/useConfig'
import { ConfigPanel } from '../../components/ConfigPanel'
import { AdminCard } from '../AdminUi'

export function AdminConfigPage({ configHook }: { configHook: ReturnType<typeof useConfig> }) {
  return (
    <AdminCard
      title="配置中心"
      subtitle="直接复用现有配置面板与 /api/v1/config 接口；保留热更新/需重启提示和配置历史。"
      className="overflow-hidden"
    >
      <div className="-mx-6 -mb-5 -mt-5">
        <ConfigPanel configHook={configHook} />
      </div>
    </AdminCard>
  )
}
