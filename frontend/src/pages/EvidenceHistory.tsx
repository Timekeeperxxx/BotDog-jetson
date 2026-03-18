/**
 * 历史证据查询页面
 * 用于查看和筛选历史告警记录
 */

import { useEffect, useMemo, useState } from 'react';
import { AlertEvent } from '../types/event';
import { getApiUrl } from '../config/api';

interface EvidenceRecord extends AlertEvent {
  evidence_id?: number;
  task_id?: number;
  created_at: string;
}

interface EvidenceListResponse {
  items: EvidenceRecord[];
  total?: number;
}

interface EvidenceDeleteResponse {
  success: boolean;
  deleted: number;
  missing_files: number;
  not_found_ids: number[];
}

export function EvidenceHistory() {
  const [evidenceList, setEvidenceList] = useState<EvidenceRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterTaskId, setFilterTaskId] = useState<string>('');
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 获取证据列表
  const fetchEvidence = async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (filterTaskId) {
        params.append('task_id', filterTaskId);
      }

      const response = await fetch(
        getApiUrl(`/api/v1/evidence?${params.toString()}`)
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: EvidenceListResponse = await response.json();
      setEvidenceList(data.items || []);
      setSelectedIds(new Set());
    } catch (err) {
      console.error('获取证据列表失败:', err);
      setError(err instanceof Error ? err.message : '未知错误');
    } finally {
      setLoading(false);
    }
  };

  const filteredList = useMemo(() => {
    return evidenceList.filter((item) => {
      if (filterSeverity !== 'all' && item.severity !== filterSeverity) {
        return false;
      }
      return true;
    });
  }, [evidenceList, filterSeverity]);

  const toggleSelected = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (filteredList.length === 0) return;
    const allSelected = filteredList.every((item) => item.evidence_id && selectedIds.has(item.evidence_id));
    if (allSelected) {
      setSelectedIds(new Set());
      return;
    }
    const next = new Set<number>();
    filteredList.forEach((item) => {
      if (item.evidence_id) next.add(item.evidence_id);
    });
    setSelectedIds(next);
  };

  const deleteByIds = async (ids: number[]) => {
    if (ids.length === 0) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await fetch(getApiUrl('/api/v1/evidence/bulk-delete'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence_ids: ids }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data: EvidenceDeleteResponse = await response.json();
      if (!data.success) {
        throw new Error('删除失败');
      }
      await fetchEvidence();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const deleteSingle = async (id?: number) => {
    if (!id) return;
    await deleteByIds([id]);
  };

  const deleteSelected = async () => {
    await deleteByIds(Array.from(selectedIds));
  };

  // 加载数据
  useEffect(() => {
    fetchEvidence();
  }, [filterTaskId]);

  // 获取严重程度颜色
  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return '#ef4444';
      case 'WARNING':
        return '#f59e0b';
      case 'INFO':
        return '#3b82f6';
      default:
        return '#64748b';
    }
  };

  // 获取严重程度图标
  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return '🚨';
      case 'WARNING':
        return '⚠️';
      case 'INFO':
        return 'ℹ️';
      default:
        return '📌';
    }
  };


  return (
    <div
      style={{
        padding: '20px',
        background: '#0f1115',
        color: '#f1f5f9',
        minHeight: '100vh',
      }}
    >
      {/* 页面标题 */}
      <div style={{ marginBottom: '24px' }}>
        <h1
          style={{
            fontSize: '24px',
            fontWeight: 'bold',
            marginBottom: '8px',
          }}
        >
          历史证据查询
        </h1>
        <p style={{ fontSize: '14px', color: '#64748b', margin: 0 }}>
          查看和筛选历史告警记录与抓拍证据
        </p>
      </div>

      {/* 筛选栏 */}
      <div
        style={{
          background: 'rgba(26, 29, 35, 0.9)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px',
          display: 'flex',
          gap: '16px',
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        {/* 任务 ID 筛选 */}
        <div style={{ flex: 1 }}>
          <label
            style={{
              display: 'block',
              fontSize: '10px',
              fontWeight: 'bold',
              color: '#94a3b8',
              textTransform: 'uppercase',
              marginBottom: '4px',
            }}
          >
            任务 ID
          </label>
          <input
            type="number"
            value={filterTaskId}
            onChange={(e) => setFilterTaskId(e.target.value)}
            placeholder="全部任务"
            style={{
              width: '100%',
              padding: '8px 12px',
              background: 'rgba(0, 0, 0, 0.3)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              borderRadius: '6px',
              color: '#e2e8f0',
              fontSize: '14px',
            }}
          />
        </div>

        {/* 严重程度筛选 */}
        <div style={{ width: '200px' }}>
          <label
            style={{
              display: 'block',
              fontSize: '10px',
              fontWeight: 'bold',
              color: '#94a3b8',
              textTransform: 'uppercase',
              marginBottom: '4px',
            }}
          >
            严重程度
          </label>
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              background: 'rgba(0, 0, 0, 0.3)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              borderRadius: '6px',
              color: '#e2e8f0',
              fontSize: '14px',
            }}
          >
            <option value="all">全部</option>
            <option value="CRITICAL">严重</option>
            <option value="WARNING">警告</option>
            <option value="INFO">信息</option>
          </select>
        </div>

        {/* 搜索按钮 */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '10px' }}>
          <button
            onClick={fetchEvidence}
            disabled={loading}
            style={{
              padding: '10px 20px',
              background: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 'bold',
              fontSize: '12px',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.5 : 1,
              textTransform: 'uppercase',
            }}
          >
            {loading ? '加载中...' : '搜索'}
          </button>
          <button
            onClick={deleteSelected}
            disabled={deleting || selectedIds.size === 0}
            style={{
              padding: '10px 20px',
              background: selectedIds.size === 0 ? 'rgba(239,68,68,0.2)' : '#ef4444',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 'bold',
              fontSize: '12px',
              cursor: selectedIds.size === 0 || deleting ? 'not-allowed' : 'pointer',
              opacity: selectedIds.size === 0 || deleting ? 0.6 : 1,
              textTransform: 'uppercase',
            }}
          >
            {deleting ? '删除中...' : `删除选中(${selectedIds.size})`}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div
          style={{
            padding: '12px',
            marginBottom: '20px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '6px',
            color: '#ef4444',
            fontSize: '12px',
          }}
        >
          {error}
        </div>
      )}

      {deleteError && (
        <div
          style={{
            padding: '12px',
            marginBottom: '20px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '6px',
            color: '#ef4444',
            fontSize: '12px',
          }}
        >
          {deleteError}
        </div>
      )}

      {/* 证据列表 */}
      <div
        style={{
          background: 'rgba(26, 29, 35, 0.9)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        {/* 列表头 */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '32px 80px 1fr 1fr 120px 120px 100px 80px',
            gap: '16px',
            padding: '12px',
            borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
            fontSize: '10px',
            fontWeight: 'bold',
            color: '#94a3b8',
            textTransform: 'uppercase',
            alignItems: 'center',
          }}
        >
          <div>
            <input
              type="checkbox"
              checked={filteredList.length > 0 && filteredList.every((item) => item.evidence_id && selectedIds.has(item.evidence_id))}
              onChange={toggleSelectAll}
            />
          </div>
          <div>严重</div>
          <div>消息</div>
          <div>事件类型</div>
          <div>时间</div>
          <div>置信度</div>
          <div>位置</div>
          <div>操作</div>
        </div>

        {/* 列表内容 */}
        {filteredList.length === 0 ? (
          <div
            style={{
              padding: '40px',
              textAlign: 'center',
              color: '#64748b',
              fontSize: '12px',
            }}
          >
            {loading
              ? '正在加载...'
              : error
              ? '加载失败'
              : '暂无记录'}
          </div>
        ) : (
          filteredList.map((item, index) => (
            <div
              key={`${item.evidence_id || index}-${item.timestamp}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '32px 80px 1fr 1fr 120px 120px 100px 80px',
                gap: '16px',
                padding: '12px',
                borderBottom:
                  index < filteredList.length - 1
                    ? '1px solid rgba(255, 255, 255, 0.05)'
                    : 'none',
                fontSize: '11px',
                alignItems: 'center',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background =
                  'rgba(255, 255, 255, 0.02)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <div>
                <input
                  type="checkbox"
                  checked={item.evidence_id ? selectedIds.has(item.evidence_id) : false}
                  onChange={() => item.evidence_id && toggleSelected(item.evidence_id)}
                />
              </div>

              {/* 严重程度 */}
              <div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <span>{getSeverityIcon(item.severity)}</span>
                  <span
                    style={{
                      color: getSeverityColor(item.severity),
                      fontWeight: 'bold',
                    }}
                  >
                    {item.severity.toLowerCase()}
                  </span>
                </div>
              </div>

              {/* 消息 */}
              <div
                style={{
                  color: '#cbd5e1',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {item.message}
              </div>

              {/* 事件类型 */}
              <div
                style={{
                  color: '#64748b',
                  fontFamily: '"JetBrains Mono", monospace',
                  fontSize: '10px',
                }}
              >
                {item.event_code}
              </div>

              {/* 时间 */}
              <div
                style={{
                  color: '#64748b',
                  fontFamily: '"JetBrains Mono", monospace',
                  fontSize: '10px',
                }}
              >
                {new Date(item.timestamp || item.created_at).toLocaleString('zh-CN', {
                  hour12: false,
                })}
              </div>

              {/* 置信度 */}
              <div>
                {item.confidence !== undefined ? (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <div
                      style={{
                        flex: 1,
                        height: '4px',
                        background: 'rgba(255, 255, 255, 0.1)',
                        borderRadius: '2px',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${item.confidence}%`,
                          height: '100%',
                          background:
                            item.confidence > 80
                              ? '#10b981'
                              : item.confidence > 60
                              ? '#f59e0b'
                              : '#ef4444',
                        }}
                      />
                    </div>
                    <span
                      style={{
                        fontSize: '10px',
                        color: '#64748b',
                        minWidth: '35px',
                      }}
                    >
                      {item.confidence.toFixed(0)}%
                    </span>
                  </div>
                ) : (
                  <span style={{ color: '#64748b' }}>-</span>
                )}
              </div>

              {/* 位置 */}
              <div>
                {item.gps ? (
                  <div
                    style={{
                      fontSize: '10px',
                      color: '#64748b',
                      fontFamily: '"JetBrains Mono", monospace',
                    }}
                  >
                    {item.gps.lat.toFixed(2)}, {item.gps.lon.toFixed(2)}
                  </div>
                ) : (
                  <span style={{ color: '#64748b' }}>-</span>
                )}
              </div>

              <div>
                <button
                  onClick={() => deleteSingle(item.evidence_id)}
                  disabled={deleting}
                  style={{
                    background: 'transparent',
                    border: '1px solid rgba(239, 68, 68, 0.4)',
                    color: '#ef4444',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    fontSize: '10px',
                    cursor: deleting ? 'not-allowed' : 'pointer',
                    opacity: deleting ? 0.6 : 1,
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 统计信息 */}
      {filteredList.length > 0 && (
        <div
          style={{
            marginTop: '16px',
            textAlign: 'center',
            fontSize: '12px',
            color: '#64748b',
          }}
        >
          显示 {filteredList.length} 条记录
        </div>
      )}
    </div>
  );
}
