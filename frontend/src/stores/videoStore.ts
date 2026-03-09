/**
 * 视频流状态管理（Zustand Store）。
 *
 * 职责边界：
 * - 管理视频流全局状态
 * - 提供 UI 订阅接口
 * - 处理视频流数据更新逻辑
 */

import { create } from 'zustand';
import type {
  VideoStreamState,
  VideoStreamStats,
  ICECandidate,
  SDPContent,
} from '../types/video';

/**
 * 视频状态接口
 */
interface VideoState {
  // 连接状态
  connection: VideoStreamState;

  // WebRTC 状态
  localSDP: SDPContent | null;
  remoteSDP: SDPContent | null;
  localCandidates: ICECandidate[];
  remoteCandidates: ICECandidate[];

  // 统计信息
  stats: VideoStreamStats;

  // 操作方法
  setConnectionStatus: (status: VideoStreamState['status']) => void;
  setClientId: (clientId: string | null) => void;
  setError: (error: string | null) => void;
  setLocalSDP: (sdp: SDPContent | null) => void;
  setRemoteSDP: (sdp: SDPContent | null) => void;
  addLocalCandidate: (candidate: ICECandidate) => void;
  addRemoteCandidate: (candidate: ICECandidate) => void;
  updateStats: (stats: Partial<VideoStreamStats>) => void;
  reset: () => void;
}

/**
 * 创建视频流 Store
 */
export const useVideoStore = create<VideoState>((set) => ({
  // 初始连接状态
  connection: {
    status: 'disconnected',
    clientId: null,
    resolution: null,
    framerate: null,
    bitrate: null,
    error: null,
  },

  // 初始 WebRTC 状态
  localSDP: null,
  remoteSDP: null,
  localCandidates: [],
  remoteCandidates: [],

  // 初始统计信息
  stats: {
    framesReceived: 0,
    framesDropped: 0,
    bytesReceived: 0,
    bitrate: 0,
    framerate: 0,
    lastFrameTime: null,
  },

  /**
   * 设置连接状态
   */
  setConnectionStatus: (status) => {
    set((state) => ({
      connection: {
        ...state.connection,
        status,
      },
    }));
  },

  /**
   * 设置客户端 ID
   */
  setClientId: (clientId) => {
    set((state) => ({
      connection: {
        ...state.connection,
        clientId,
      },
    }));
  },

  /**
   * 设置错误信息
   */
  setError: (error) => {
    set((state) => ({
      connection: {
        ...state.connection,
        error,
        status: error ? 'error' : state.connection.status,
      },
    }));
  },

  /**
   * 设置本地 SDP
   */
  setLocalSDP: (sdp) => {
    set({ localSDP: sdp });
  },

  /**
   * 设置远程 SDP
   */
  setRemoteSDP: (sdp) => {
    set({ remoteSDP: sdp });
  },

  /**
   * 添加本地 ICE 候选
   */
  addLocalCandidate: (candidate) => {
    set((state) => ({
      localCandidates: [...state.localCandidates, candidate],
    }));
  },

  /**
   * 添加远程 ICE 候选
   */
  addRemoteCandidate: (candidate) => {
    set((state) => ({
      remoteCandidates: [...state.remoteCandidates, candidate],
    }));
  },

  /**
   * 更新统计信息
   */
  updateStats: (newStats) => {
    set((state) => ({
      stats: {
        ...state.stats,
        ...newStats,
      },
    }));
  },

  /**
   * 重置状态
   */
  reset: () => {
    set({
      connection: {
        status: 'disconnected',
        clientId: null,
        resolution: null,
        framerate: null,
        bitrate: null,
        error: null,
      },
      localSDP: null,
      remoteSDP: null,
      localCandidates: [],
      remoteCandidates: [],
      stats: {
        framesReceived: 0,
        framesDropped: 0,
        bytesReceived: 0,
        bitrate: 0,
        framerate: 0,
        lastFrameTime: null,
      },
    });
  },
}));
