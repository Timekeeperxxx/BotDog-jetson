import time
import uuid
from cyclonedds.domain import DomainParticipant
from cyclonedds.topic import Topic
from cyclonedds.idl import IdlStruct
import dataclasses

# 使用一个极其随机的名称，确保绝不冲突
unique_id = uuid.uuid4().hex[:8]
type_name = f"Type_{unique_id}"
topic_name = f"Topic_{unique_id}"

@dataclasses.dataclass
class SimpleMsg(IdlStruct, typename=type_name):
    id: int

try:
    # 强制不使用任何缓存，新开一个 Domain
    dp = DomainParticipant(domain_id=15)
    print(f"1. Participant Created in Domain 15")
    
    # 尝试创建 Topic
    tp = Topic(dp, topic_name, SimpleMsg)
    print(f"2. Topic '{topic_name}' Created Successfully!")
    
except Exception as e:
    print(f"✗ 仍然失败: {e}")