// 测试导入是否正常工作
import { AlertEvent, EventMessage, EventWebSocketStatus } from './event';

const test: AlertEvent = {
  event_type: 'test',
  event_code: 'TEST',
  severity: 'INFO',
  message: 'test message',
  timestamp: '2024-01-01',
};

console.log('Import test passed:', test);
