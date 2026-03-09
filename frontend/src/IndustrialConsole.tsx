/**
 * BotDog 机器狗控制终端 - 专业工业版
 * 按照 docs/04_ui_prototype.html 规范实现
 * 接入真实遥测数据和WebSocket连接
 */

import { useState, useEffect } from 'react';
import { useBotDogData } from './hooks/useBotDogData';

// ==================== 顶部状态栏 ====================
function HeaderBar({
  latency,
  rssi,
  temperature,
  battery,
  onEmergencyStop
}: {
  latency: string;
  rssi: string;
  temperature: string;
  battery: string;
  onEmergencyStop: () => void;
}) {
  const [currentTime, setCurrentTime] = useState('');

  useEffect(() => {
    const updateTime = () => {
      setCurrentTime(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '0.75rem 1.5rem',
      background: 'rgba(26, 29, 35, 0.9)',
      border: '1px solid rgba(255, 255, 255, 0.05)',
      borderRadius: '8px',
      backdropFilter: 'blur(20px)',
    }}>
      {/* 左侧：系统信息 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          paddingRight: '32px',
          borderRight: '1px solid rgba(255, 255, 255, 0.05)',
        }}>
          <span style={{ color: '#60a5fa', fontSize: '18px' }}>🔌</span>
          <div>
            <h1 style={{
              fontSize: '14px',
              fontWeight: 'bold',
              letterSpacing: 'tight',
              textTransform: 'uppercase',
              margin: 0,
              color: '#e2e8f0',
            }}>
              机器狗控制系统 <span style={{ color: '#3b82f6' }}>v5.0-专业版</span>
            </h1>
            <p style={{
              fontSize: '10px',
              color: '#64748b',
              fontWeight: '500',
              margin: '2px 0 0 0',
            }}>
              设备编号: SD-082-ALPHA
            </p>
          </div>
        </div>

        {/* 性能指标 */}
        <div style={{ display: 'flex', gap: '40px' }}>
          <MetricItem label="链路延迟" value={latency} />
          <MetricItem label="信号强度" value={rssi} />
          <MetricItem label="核心温度" value={temperature} color={parseFloat(temperature) > 42 ? '#ef4444' : '#fb923c'} />
          <MetricItem label="剩余电量" value={battery} color={parseFloat(battery) < 20 ? '#ef4444' : '#10b981'} />
        </div>
      </div>

      {/* 右侧：时间 + 急停 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        <div style={{ textAlign: 'right', marginRight: '16px' }}>
          <span style={{
            fontSize: '9px',
            color: '#64748b',
            textTransform: 'uppercase',
            fontWeight: 'bold',
            display: 'block',
          }}>
            终端时间
          </span>
          <div style={{
            fontSize: '14px',
            fontWeight: 'bold',
            fontFamily: '"JetBrains Mono", monospace',
            color: '#e2e8f0',
          }}>
            {currentTime}
          </div>
        </div>
        <button
          onClick={onEmergencyStop}
          style={{
            background: '#b91c1c',
            borderBottom: '4px solid #7f1d1d',
            transition: 'all 0.1s',
            padding: '8px 20px',
            borderRadius: '6px',
            color: 'white',
            fontWeight: 'bold',
            textTransform: 'uppercase',
            fontSize: '10px',
            letterSpacing: '1px',
            cursor: 'pointer',
            border: 'none',
          }}
        >
          紧急制动
        </button>
      </div>
    </header>
  );
}

function MetricItem({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '2px',
    }}>
      <span style={{
        fontSize: '9px',
        color: '#64748b',
        fontWeight: 'bold',
        textTransform: 'uppercase',
      }}>
        {label}
      </span>
      <span style={{
        fontSize: '12px',
        fontFamily: '"JetBrains Mono", monospace',
        fontWeight: 'bold',
        color: color || '#e2e8f0',
      }}>
        {value}
      </span>
    </div>
  );
}

// ==================== 左侧栏 ====================
function LeftPanel({ snapshots }: { snapshots: Array<{ id: string; confidence: number; created_at: number; event_type?: string }> }) {
  return (
    <aside style={{
      width: '256px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
    }}>
      {/* 地图占位区域 */}
      <div style={{
        height: '160px',
        background: 'rgba(15, 23, 42, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          opacity: 0.2,
          backgroundImage: 'radial-gradient(rgba(255, 255, 255, 1) 1px, transparent 1px)',
          backgroundSize: '16px 16px',
        }} />
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
        }}>
          <span style={{
            fontSize: '10px',
            color: '#64748b',
            fontFamily: '"JetBrains Mono", monospace',
          }}>
            地图模块离线
          </span>
        </div>
        <div style={{
          position: 'absolute',
          bottom: '8px',
          left: '8px',
          fontSize: '9px',
          color: '#94a3b8',
          fontFamily: '"JetBrains Mono", monospace',
        }}>
          坐标: 39.91N / 116.40E
        </div>
      </div>

      {/* 实时抓拍列表 */}
      <SnapshotList snapshots={snapshots} />
    </aside>
  );
}

function SnapshotList({ snapshots }: { snapshots: Array<{ id: string; confidence: number; created_at: number; event_type?: string }> }) {
  return (
    <div style={{
      flex: 1,
      background: 'rgba(26, 29, 35, 0.9)',
      border: '1px solid rgba(255, 255, 255, 0.05)',
      borderRadius: '8px',
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
    }}>
      <div style={{
        padding: '16px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}>
        <h3 style={{
          fontSize: '10px',
          fontWeight: 'bold',
          color: '#94a3b8',
          textTransform: 'uppercase',
          letterSpacing: '2px',
          margin: 0,
        }}>
          实时抓拍
        </h3>
        <span style={{
          fontSize: '9px',
          color: '#3b82f6',
          fontWeight: 'bold',
          textTransform: 'uppercase',
          cursor: 'pointer',
        }}>
          历史存档
        </span>
      </div>
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '8px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        {snapshots.length === 0 ? (
          <div style={{
            textAlign: 'center',
            color: '#64748b',
            fontSize: '10px',
            padding: '20px',
          }}>
            等待识别事件...
          </div>
        ) : (
          snapshots.map((snapshot) => (
            <div key={snapshot.id} style={{
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              padding: '8px',
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}>
              <div style={{
                width: '40px',
                height: '40px',
                background: 'black',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}>
                <span style={{ fontSize: '20px', opacity: 0.1 }}>👤</span>
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{
                  fontSize: '10px',
                  fontWeight: 'bold',
                  color: '#cbd5e1',
                  marginBottom: '2px',
                }}>
                  {snapshot.event_type || '未知事件'}: {snapshot.id}
                </div>
                <div style={{
                  fontSize: '8px',
                  color: '#64748b',
                  fontFamily: '"JetBrains Mono", monospace',
                }}>
                  置信度: {snapshot.confidence}% | {new Date(snapshot.created_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ==================== 中央视频区域 ====================
function VideoSection({
  attitude,
  altitude,
  groundspeed
}: {
  attitude?: { pitch: number; roll: number; yaw: number };
  altitude?: number;
  groundspeed?: number;
}) {
  const [isFullscreen, setIsFullscreen] = useState(false);

  const handleFullscreen = () => {
    const newState = !isFullscreen;
    setIsFullscreen(newState);

    // 真正的全屏API
    if (newState) {
      const elem = document.documentElement;
      if (elem.requestFullscreen) {
        elem.requestFullscreen().catch((err) => {
          console.error('全屏请求失败:', err);
          // 如果请求失败，仍然使用CSS模拟
        });
      } else if ((elem as any).webkitRequestFullscreen) {
        (elem as any).webkitRequestFullscreen();
      }
    } else {
      // 退出全屏
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if ((document as any).webkitExitFullscreen) {
        (document as any).webkitExitFullscreen();
      }
    }
  };

  // ESC键退出全屏
  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };

    if (isFullscreen) {
      document.addEventListener('keydown', handleEsc);
      return () => document.removeEventListener('keydown', handleEsc);
    }
  }, [isFullscreen]);

  // 监听全屏状态变化
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isCurrentlyFullscreen = !!(
        document.fullscreenElement ||
        (document as any).webkitFullscreenElement
      );
      setIsFullscreen(isCurrentlyFullscreen);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
    };
  }, []);

  // 全屏时隐藏body的padding
  useEffect(() => {
    if (isFullscreen) {
      document.body.style.padding = '0';
    } else {
      document.body.style.padding = '20px';
    }

    return () => {
      document.body.style.padding = '20px';
    };
  }, [isFullscreen]);

  const containerStyle = isFullscreen ? {
    position: 'fixed' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100vw',
    height: '100vh',
    zIndex: 9999,
    borderRadius: 0,
    border: 'none',
    margin: 0,
  } : {
    flex: 1,
    background: 'black',
    border: '1px solid rgba(255, 255, 255, 0.05)',
    borderRadius: '8px',
    position: 'relative' as const,
    overflow: 'hidden',
  };

  // 计算航向角显示
  const getHeadingDisplay = () => {
    if (!attitude) return '184° / 南';
    const heading = Math.round(attitude.yaw);
    const directions = ['北', '东北', '东', '东南', '南', '西南', '西', '西北'];
    const index = Math.round(heading / 45) % 8;
    return `${heading}° / ${directions[index]}`;
  };

  return (
    <section style={containerStyle}>
      {/* 全屏控制按钮 */}
      <button
        onClick={handleFullscreen}
        style={{
          position: 'absolute',
          top: '16px',
          right: '16px',
          zIndex: 60,
          width: '32px',
          height: '32px',
          borderRadius: '6px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(0, 0, 0, 0.4)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          backdropFilter: 'blur(4px)',
          transition: 'all 0.2s',
          color: 'rgba(255, 255, 255, 0.8)',
          cursor: 'pointer',
          fontSize: '12px',
        }}
        title={isFullscreen ? '退出全屏 (ESC)' : '全屏显示'}
      >
        {isFullscreen ? '↙️' : '⛶'}
      </button>

      {/* HUD 仪表 */}
      <VideoHUD
        attitude={attitude}
        altitude={altitude}
        groundspeed={groundspeed}
        heading={getHeadingDisplay()}
      />

      {/* 视频标签 */}
      <div style={{
        position: 'absolute',
        top: '16px',
        left: '16px',
        display: 'flex',
        gap: '8px',
      }}>
        <div style={{
          background: 'rgba(37, 99, 235, 0.2)',
          color: '#60a5fa',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '9px',
          fontWeight: 'bold',
          border: '1px solid rgba(59, 130, 246, 0.3)',
        }}>
          4K 实时流
        </div>
        {isFullscreen && (
          <div style={{
            background: 'rgba(255, 255, 255, 0.05)',
            color: '#94a3b8',
            padding: '4px 8px',
            borderRadius: '4px',
            fontSize: '9px',
            fontWeight: 'bold',
          }}>
            全屏监视中
          </div>
        )}
      </div>

      {/* 十字准星 */}
      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        opacity: 0.05,
        fontSize: '160px',
      }}>
        ✚
      </div>
    </section>
  );
}

function VideoHUD({
  attitude,
  altitude,
  groundspeed,
  heading
}: {
  attitude?: { pitch: number; roll: number; yaw: number };
  altitude?: number;
  groundspeed?: number;
  heading?: string;
}) {
  // 根据实际数据计算刻度范围
  const alt = altitude || 1.2;
  const speed = groundspeed || 0.8;

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      pointerEvents: 'none',
      zIndex: 50,
    }}>
      {/* 姿态仪中心 */}
      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        width: '300px',
        height: '300px',
        transform: 'translate(-50%, -50%)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '50%',
      }} />

      {/* 姿态线 */}
      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        width: '240px',
        height: '1px',
        background: 'rgba(255, 255, 255, 0.2)',
        transform: `translate(-50%, -50%) rotate(${attitude?.roll || 0}deg)`,
      }} />

      {/* 高度刻度 */}
      <div style={{
        position: 'absolute',
        left: '40px',
        top: '50%',
        transform: 'translateY(-50%)',
        height: '160px',
        width: '48px',
        borderLeft: '1px solid rgba(255, 255, 255, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '8px 0',
      }}>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.4)',
        }}>
          {(alt + 0.3).toFixed(1)}米
        </span>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.8)',
          fontWeight: 'bold',
        }}>
          {alt.toFixed(1)}米
        </span>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.4)',
        }}>
          {(alt - 0.3).toFixed(1)}米
        </span>
      </div>

      {/* 速度刻度 */}
      <div style={{
        position: 'absolute',
        right: '40px',
        top: '50%',
        transform: 'translateY(-50%)',
        height: '160px',
        width: '48px',
        borderRight: '1px solid rgba(255, 255, 255, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '8px 0',
        textAlign: 'right',
      }}>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.4)',
        }}>
          {(speed + 0.4).toFixed(1)} 米/秒
        </span>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.8)',
          fontWeight: 'bold',
        }}>
          {speed.toFixed(1)} 米/秒
        </span>
        <span style={{
          fontSize: '10px',
          fontFamily: '"JetBrains Mono", monospace',
          color: 'rgba(255, 255, 255, 0.4)',
        }}>
          {(speed - 0.4).toFixed(1)} 米/秒
        </span>
      </div>

      {/* 底部信息栏 */}
      <div style={{
        position: 'absolute',
        bottom: '24px',
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        gap: '40px',
        alignItems: 'center',
        background: 'rgba(0, 0, 0, 0.4)',
        padding: '8px 24px',
        borderRadius: '9999px',
        border: '1px solid rgba(255, 255, 255, 0.05)',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <span style={{
            fontSize: '8px',
            color: '#64748b',
            textTransform: 'uppercase',
            fontWeight: 'bold',
          }}>
            巡检模式
          </span>
          <span style={{
            fontSize: '10px',
            fontWeight: 'bold',
            color: '#60a5fa',
          }}>
            全自动巡航
          </span>
        </div>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          borderLeft: '1px solid rgba(255, 255, 255, 0.1)',
          paddingLeft: '40px',
        }}>
          <span style={{
            fontSize: '8px',
            color: '#64748b',
            textTransform: 'uppercase',
            fontWeight: 'bold',
          }}>
            航向角
          </span>
          <span style={{
            fontSize: '10px',
            fontWeight: 'bold',
            fontFamily: '"JetBrains Mono", monospace',
          }}>
            {heading}
          </span>
        </div>
      </div>
    </div>
  );
}

// ==================== 右侧栏 ====================
function RightPanel({
  motors,
  logs
}: {
  motors: Array<{ name: string; temp_c: number; current_a: number; load_pct: number }>;
  logs: Array<{ timestamp: number; level: 'info' | 'warning' | 'error'; module: string; message: string }>;
}) {
  return (
    <aside style={{
      width: '256px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
    }}>
      {/* 执行器状态 */}
      <div style={{
        background: 'rgba(26, 29, 35, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        padding: '16px',
      }}>
        <h3 style={{
          fontSize: '10px',
          fontWeight: 'bold',
          color: '#94a3b8',
          textTransform: 'uppercase',
          letterSpacing: '2px',
          marginBottom: '12px',
        }}>
          执行器状态
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {motors.map((motor, index) => (
            <MotorItem
              key={index}
              name={motor.name}
              temp={`${motor.temp_c.toFixed(1)}°C`}
              current={`${motor.current_a.toFixed(1)}A`}
              load={motor.load_pct}
            />
          ))}
        </div>
      </div>

      {/* 系统日志 */}
      <div style={{
        flex: 1,
        background: 'rgba(26, 29, 35, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}>
        <div style={{
          padding: '16px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
          background: 'rgba(255, 255, 255, 0.05)',
        }}>
          <h3 style={{
            fontSize: '10px',
            fontWeight: 'bold',
            color: '#94a3b8',
            textTransform: 'uppercase',
            letterSpacing: '2px',
            margin: 0,
          }}>
            系统日志
          </h3>
        </div>
        <div style={{
          flex: 1,
          padding: '12px',
          overflowY: 'auto',
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: '9px',
          color: '#64748b',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}>
          {logs.map((log, index) => {
            const levelColor = log.level === 'error' ? '#ef4444' : log.level === 'warning' ? '#f59e0b' : '#64748b';
            return (
              <div key={index} style={{ display: 'flex', gap: '8px' }}>
                <span style={{
                  color: 'rgba(255, 255, 255, 0.2)',
                  flexShrink: 0,
                }}>
                  {new Date(log.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                </span>
                <span style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  color: levelColor,
                }}>
                  [{log.module}] {log.message}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

function MotorItem({ name, temp, current, load }: { name: string; temp: string; current: string; load: number }) {
  const tempValue = parseFloat(temp);
  const tempColor = tempValue > 42 ? '#ef4444' : tempValue > 38 ? '#f59e0b' : '#64748b';

  return (
    <div>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '10px',
      }}>
        <span style={{ color: '#64748b' }}>{name}</span>
        <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>
          <span style={{ color: tempColor }}>{temp}</span> / <span style={{ color: '#64748b' }}>{current}</span>
        </span>
      </div>
      <div style={{
        width: '100%',
        background: 'rgba(255, 255, 255, 0.05)',
        height: '4px',
        borderRadius: '9999px',
        overflow: 'hidden',
      }}>
        <div style={{
          background: load > 80 ? '#ef4444' : load > 60 ? '#f59e0b' : '#3b82f6',
          height: '100%',
          width: `${load}%`,
        }} />
      </div>
    </div>
  );
}

// ==================== 底部状态条 ====================
function FooterBar({ systemStatus, isConnected }: { systemStatus: { status: string; uptime: string }; isConnected: boolean }) {
  const statusConfig = {
    'DISCONNECTED': { icon: '🔴', text: '未连接', color: '#ef4444' },
    'STANDBY': { icon: '🟡', text: '待机中', color: '#f59e0b' },
    'IN_MISSION': { icon: '🟢', text: '任务中', color: '#10b981' },
    'E_STOP_TRIGGERED': { icon: '🚨', text: '紧急停止', color: '#ef4444' },
  };

  const config = statusConfig[systemStatus.status as keyof typeof statusConfig] || statusConfig.DISCONNECTED;

  return (
    <footer style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '4px 16px',
      fontSize: '9px',
      color: '#475569',
      textTransform: 'uppercase',
      letterSpacing: '2px',
    }}>
      <div style={{ display: 'flex', gap: '16px' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: config.color }}>
          {config.icon} {config.text}
        </span>
        <span>运行时间: {systemStatus.uptime}</span>
      </div>
      <span>安全加密层: AES-XTS-256 {isConnected && '| 实时连接中'}</span>
    </footer>
  );
}

// ==================== 主应用 ====================
export default function IndustrialConsole() {
  const {
    telemetry,
    isConnected,
    snapshots,
    logs,
    systemStatus,
    triggerEmergencyStop,
  } = useBotDogData();

  // 全屏时移除外边距
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const checkFullscreen = () => {
      const isCurrentlyFullscreen = !!(
        document.fullscreenElement ||
        (document as any).webkitFullscreenElement
      );
      setIsFullscreen(isCurrentlyFullscreen);
    };

    checkFullscreen();
    document.addEventListener('fullscreenchange', checkFullscreen);
    document.addEventListener('webkitfullscreenchange', checkFullscreen);

    return () => {
      document.removeEventListener('fullscreenchange', checkFullscreen);
      document.removeEventListener('webkitfullscreenchange', checkFullscreen);
    };
  }, []);

  return (
    <div style={{
      backgroundColor: '#0f1115',
      color: '#f1f5f9',
      fontFamily: '"Inter", -apple-system, "Microsoft YaHei", sans-serif',
      overflow: 'hidden',
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      margin: 0,
      padding: isFullscreen ? 0 : '20px',
      gap: '16px',
    }}>
      <HeaderBar
        latency={telemetry ? `${telemetry.latency_ms}ms` : '--'}
        rssi={telemetry ? `${telemetry.rssi_dbm} dBm` : '--'}
        temperature={telemetry ? `${telemetry.core_temp_c.toFixed(1)}°C` : '--'}
        battery={telemetry ? `${telemetry.battery_pct.toFixed(1)}%` : '--'}
        onEmergencyStop={triggerEmergencyStop}
      />

      <main style={{
        flex: 1,
        display: 'flex',
        gap: '16px',
        minHeight: 0,
      }}>
        <LeftPanel snapshots={snapshots} />
        <VideoSection
          attitude={telemetry?.attitude}
          altitude={telemetry?.position.alt}
          groundspeed={telemetry?.position.groundspeed}
        />
        <RightPanel
          motors={telemetry?.motors || []}
          logs={logs}
        />
      </main>

      <FooterBar
        systemStatus={systemStatus}
        isConnected={isConnected}
      />
    </div>
  );
}