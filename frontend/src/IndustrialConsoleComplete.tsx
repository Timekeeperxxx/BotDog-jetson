/**
 * BotDog 机器狗控制终端 - 完整集成版本
 * 包含完整的前后端交互、WebSocket连接和WebRTC视频流
 */

import { useState, useEffect } from 'react';
import { useBotDogWebSocket } from './hooks/useBotDogWebSocket';
import { useWebRTCVideo } from './hooks/useWebRTCVideo';
import { SnapshotList } from './components/SnapshotList';
import { ControlPanel } from './components/ControlPanel';
import { ConfigPanel } from './components/ConfigPanel';

// ==================== 顶部状态栏 ====================
function HeaderBar({
  latency,
  rssi,
  temperature,
  battery,
  onEmergencyStop,
  onToggleFullscreen,
  onOpenConfig,
  isConnected
}: {
  latency: string;
  rssi: string;
  temperature: string;
  battery: string;
  onEmergencyStop: () => void;
  onToggleFullscreen: () => void;
  onOpenConfig: () => void;
  isConnected: boolean;
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
              color: isConnected ? '#10b981' : '#64748b',
              fontWeight: '500',
              margin: '2px 0 0 0',
            }}>
              设备编号: SD-082-ALPHA {isConnected ? '● 已连接' : '○ 未连接'}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '40px' }}>
          <MetricItem label="链路延迟" value={latency} />
          <MetricItem label="信号强度" value={rssi} />
          <MetricItem label="核心温度" value={temperature} color={parseFloat(temperature) > 42 ? '#ef4444' : '#fb923c'} />
          <MetricItem label="剩余电量" value={battery} color={parseFloat(battery) < 20 ? '#ef4444' : '#10b981'} />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        <div style={{ textAlign: 'right', marginRight: '16px' }}>
          <span style={{ fontSize: '9px', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold', display: 'block' }}>
            终端时间
          </span>
          <div style={{ fontSize: '14px', fontWeight: 'bold', fontFamily: '"JetBrains Mono", monospace', color: '#e2e8f0' }}>
            {currentTime}
          </div>
        </div>
        <button
          onClick={onOpenConfig}
          style={{
            background: 'rgba(59, 130, 246, 0.2)',
            border: '1px solid rgba(59, 130, 246, 0.4)',
            padding: '8px 16px',
            borderRadius: '6px',
            color: '#93c5fd',
            fontWeight: 'bold',
            textTransform: 'uppercase',
            fontSize: '10px',
            letterSpacing: '1px',
            cursor: 'pointer',
            marginRight: '12px',
          }}
          title="系统配置"
        >
          ⚙️ 配置
        </button>
        <button
          onClick={onToggleFullscreen}
          style={{
            background: '#3b82f6',
            borderBottom: '4px solid #2563eb',
            transition: 'all 0.1s',
            padding: '8px 16px',
            borderRadius: '6px',
            color: 'white',
            fontWeight: 'bold',
            textTransform: 'uppercase',
            fontSize: '10px',
            letterSpacing: '1px',
            cursor: 'pointer',
            border: 'none',
            marginRight: '12px',
          }}
          title="全屏显示 (F11)"
        >
          ⛶ 全屏
        </button>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      <span style={{ fontSize: '9px', color: '#64748b', fontWeight: 'bold', textTransform: 'uppercase' }}>
        {label}
      </span>
      <span style={{ fontSize: '12px', fontFamily: '"JetBrains Mono", monospace', fontWeight: 'bold', color: color || '#e2e8f0' }}>
        {value}
      </span>
    </div>
  );
}

// ==================== 左侧栏 ====================
function LeftPanel({ snapshots }: { snapshots: any[] }) {
  return (
    <aside style={{
      width: '256px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
    }}>
      {/* 使用 SnapshotList 组件 */}
      <SnapshotList maxItems={50} autoScroll={true} />
    </aside>
  );
}
// ==================== 中央视频区域 ====================
function VideoSection({
  attitude,
  altitude,
  groundspeed,
  isFullscreen,
  videoRef,
  webrtcStatus,
  isConnected
}: {
  attitude?: { pitch: number; roll: number; yaw: number };
  altitude?: number;
  groundspeed?: number;
  isFullscreen: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  webrtcStatus: { status: string; error: string | null };
  isConnected: boolean;
}) {
  const getHeadingDisplay = () => {
    if (!attitude) return "184° / 南";
    const heading = Math.round(attitude.yaw);
    const directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"];
    const index = Math.round(heading / 45) % 8;
    return `${heading}° / ${directions[index]}`;
  };

  const alt = altitude || 1.2;
  const speed = groundspeed || 0.8;

  const webrtcConfig: any = {
    'disconnected': { color: '#ef4444', text: '未连接' },
    'connecting': { color: '#f59e0b', text: '连接中...' },
    'connected': { color: '#10b981', text: '已连接' },
    'error': { color: '#ef4444', text: webrtcStatus.error || '错误' },
  };

  const currentWebrtcStatus = webrtcConfig[webrtcStatus.status as keyof typeof webrtcConfig] || webrtcConfig.disconnected;

  return (
    <section style={isFullscreen ? {
      position: 'fixed',
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
      padding: 0,
      background: 'black',
    } : {
      flex: 1,
      background: 'black',
      border: '1px solid ' + (isConnected ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255, 255, 255, 0.05)'),
      borderRadius: '8px',
      position: 'relative',
    }}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          background: 'black',
        }}
      />

      {webrtcStatus.status !== 'connected' && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(15, 23, 42, 0.9)',
          zIndex: 5,
        }}>
          <div style={{ fontSize: '48px', marginBottom: '1rem', opacity: 0.5 }}>📹</div>
          <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#e2e8f0', marginBottom: '0.5rem' }}>
            视频流 {currentWebrtcStatus.text}
          </div>
          {webrtcStatus.error && (
            <div style={{
              fontSize: '14px',
              color: '#ef4444',
              marginBottom: '1rem',
              padding: '0.5rem 1rem',
              background: 'rgba(239, 68, 68, 0.1)',
              borderRadius: '4px',
            }}>
              {webrtcStatus.error}
            </div>
          )}
          <div style={{ fontSize: '12px', color: '#64748b' }}>
            {isConnected ? '等待WebRTC连接...' : '等待后端连接...'}
          </div>
        </div>
      )}

      <div style={{
        position: 'absolute',
        top: '16px',
        left: '16px',
        display: 'flex',
        gap: '8px',
        zIndex: 10,
      }}>
        <div style={{
          background: 'rgba(37, 99, 235, 0.2)',
          color: '#60a5fa',
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '9px',
          fontWeight: 'bold',
          border: `1px solid rgba(59, 130, 246, 0.3)`,
        }}>
          4K 实时流
        </div>
        <div style={{
          background: 'rgba(255, 255, 255, 0.05)',
          color: currentWebrtcStatus.color,
          padding: '4px 8px',
          borderRadius: '4px',
          fontSize: '9px',
          fontWeight: 'bold',
        }}>
          {currentWebrtcStatus.text}
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
            按 ESC 或 F11 退出全屏
          </div>
        )}
      </div>

      {/* HUD 仪表 */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: 'none',
        zIndex: 50,
      }}>
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
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: '240px',
          height: '1px',
          background: 'rgba(255, 255, 255, 0.2)',
          transform: `translate(-50%, -50%) rotate(${attitude?.roll || 0}deg)`,
        }} />
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
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.4)' }}>
            {(alt + 0.3).toFixed(1)}米
          </span>
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.8)', fontWeight: 'bold' }}>
            {alt.toFixed(1)}米
          </span>
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.4)' }}>
            {(alt - 0.3).toFixed(1)}米
          </span>
        </div>
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
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.4)' }}>
            {(speed + 0.4).toFixed(1)} 米/秒
          </span>
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.8)', fontWeight: 'bold' }}>
            {speed.toFixed(1)} 米/秒
          </span>
          <span style={{ fontSize: '10px', fontFamily: '"JetBrains Mono", monospace', color: 'rgba(255, 255, 255, 0.4)' }}>
            {(speed - 0.4).toFixed(1)} 米/秒
          </span>
        </div>
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
            <span style={{ fontSize: '8px', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold' }}>
              巡检模式
            </span>
            <span style={{ fontSize: '10px', fontWeight: 'bold', color: '#60a5fa' }}>
              全自动巡航
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', borderLeft: '1px solid rgba(255, 255, 255, 0.1)', paddingLeft: '40px' }}>
            <span style={{ fontSize: '8px', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold' }}>
              航向角
            </span>
            <span style={{ fontSize: '10px', fontWeight: 'bold', fontFamily: '"JetBrains Mono", monospace' }}>
              {getHeadingDisplay()}
            </span>
          </div>
        </div>
      </div>

      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        opacity: 0.05,
        fontSize: '160px',
        pointerEvents: 'none',
      }}>
        ✚
      </div>
    </section>
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
      {/* 控制面板 */}
      <ControlPanel />

      <div style={{
        background: 'rgba(26, 29, 35, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        padding: '16px',
      }}>
        <h3 style={{ fontSize: '10px', fontWeight: 'bold', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '2px', marginBottom: '12px' }}>
          执行器状态
        </h3>
        {motors.length === 0 ? (
          <div style={{ fontSize: '10px', color: '#64748b', textAlign: 'center', padding: '1rem' }}>
            等待电机数据...
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {motors.map((motor, index) => (
              <div key={index}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '10px' }}>
                  <span style={{ color: '#64748b' }}>{motor.name}</span>
                  <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>
                    <span style={{ color: motor.temp_c > 42 ? '#ef4444' : motor.temp_c > 38 ? '#f59e0b' : '#64748b' }}>
                      {motor.temp_c.toFixed(1)}°C
                    </span> / <span style={{ color: '#64748b' }}>{motor.current_a.toFixed(1)}A</span>
                  </span>
                </div>
                <div style={{ width: '100%', background: 'rgba(255, 255, 255, 0.05)', height: '4px', borderRadius: '9999px', overflow: 'hidden' }}>
                  <div style={{
                    background: motor.load_pct > 80 ? '#ef4444' : motor.load_pct > 60 ? '#f59e0b' : '#3b82f6',
                    height: '100%',
                    width: `${motor.load_pct}%`,
                  }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{
        flex: 1,
        background: 'rgba(26, 29, 35, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}>
        <div style={{ padding: '16px', borderBottom: '1px solid rgba(255, 255, 255, 0.05)', background: 'rgba(255, 255, 255, 0.05)' }}>
          <h3 style={{ fontSize: '10px', fontWeight: 'bold', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '2px', margin: 0 }}>
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
          {logs.length === 0 ? (
            <div style={{ fontSize: '10px', color: '#64748b', textAlign: 'center', padding: '20px' }}>
              等待日志...
            </div>
          ) : (
            logs.map((log, index) => {
              const levelColor = log.level === 'error' ? '#ef4444' : log.level === 'warning' ? '#f59e0b' : '#64748b';
              return (
                <div key={index} style={{ display: 'flex', gap: '8px' }}>
                  <span style={{ color: 'rgba(255, 255, 255, 0.2)', flexShrink: 0 }}>
                    {new Date(log.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                  </span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: levelColor }}>
                    [{log.module}] {log.message}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
}

// ==================== 底部状态条 ====================
function FooterBar({ systemStatus, isConnected }: { systemStatus: { status: string; uptime: string }; isConnected: boolean }) {
  const statusConfig: any = {
    'DISCONNECTED': { icon: '🔴', text: '未连接', color: '#ef4444' },
    'STANDBY': { icon: '🟡', text: '待机中', color: '#f59e0b' },
    'IN_MISSION': { icon: '🟢', text: '任务中', color: '#10b981' },
    'E_STOP_TRIGGERED': { icon: '🚨', text: '紧急停止', color: '#ef4444' },
  };

  const config = statusConfig[systemStatus.status] || statusConfig.DISCONNECTED;

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
export default function IndustrialConsoleComplete() {
  const {
    telemetry,
    isConnected,
    snapshots,
    logs,
    systemStatus,
    triggerEmergencyStop,
    connect: connectWs,
    disconnect: disconnectWs,
  } = useBotDogWebSocket();

  const { status: webrtcStatus, videoRef, connect: connectWebRTC, disconnect: disconnectWebRTC } = useWebRTCVideo();

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showConfigPanel, setShowConfigPanel] = useState(false);

  useEffect(() => {
    connectWs();
    return () => {
      disconnectWs();
    };
  }, []);

  // WebRTC 连接与遥测连接解耦，独立尝试连接
  useEffect(() => {
    connectWebRTC();
    return () => {
      disconnectWebRTC();
    };
  }, []);

  // 全屏切换函数
  const toggleFullscreen = () => {
    if (!isFullscreen) {
      const elem = document.documentElement;
      if (elem.requestFullscreen) {
        elem.requestFullscreen().catch(console.error);
      } else if ((elem as any).webkitRequestFullscreen) {
        (elem as any).webkitRequestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if ((document as any).webkitExitFullscreen) {
        (document as any).webkitExitFullscreen();
      }
    }
  };

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
        onToggleFullscreen={toggleFullscreen}
        onOpenConfig={() => setShowConfigPanel(true)}
        isConnected={isConnected}
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
          isFullscreen={isFullscreen}
          videoRef={videoRef}
          webrtcStatus={webrtcStatus}
          isConnected={isConnected}
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

      {/* 配置面板模态框 */}
      {showConfigPanel && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.85)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            width: '800px',
            maxHeight: '90vh',
            overflow: 'auto',
            borderRadius: '8px',
          }}>
            <ConfigPanel />
            <button
              onClick={() => setShowConfigPanel(false)}
              style={{
                marginTop: '16px',
                padding: '12px 24px',
                background: 'rgba(239, 68, 68, 0.2)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '6px',
                color: '#fca5a5',
                fontSize: '12px',
                fontWeight: 'bold',
                cursor: 'pointer',
                width: '100%',
              }}
            >
              ✕ 关闭配置
            </button>
          </div>
        </div>
      )}
    </div>
  );
}