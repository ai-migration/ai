from dotenv import load_dotenv
import os
from confluent_kafka import Consumer, KafkaException
import json
from security.app.log import Logger
from security.app.producer import MessageProducer
from security.app.security_pipeline import run_security_pipeline
load_dotenv()

class MessageConsumer:
    def __init__(self):
        self.logger = Logger(name='translate').logger
        self.broker = os.environ.get('KAFKA_SERVER')
        self.topic = os.environ.get('CONS_TOPIC')
        self.group_id = os.environ.get('GROUP_ID')
        self.auto_offset_reset = os.environ.get('AUTO_OFFSET_RESET')
        self.consumer = Consumer({
                                    'bootstrap.servers': self.broker,
                                    'group.id': self.group_id, # consumer의 id
                                    'auto.offset.reset': self.auto_offset_reset  # 처음 실행시 가장 마지막 offset부터
                                })
        self.consumer.subscribe([self.topic])
        self.producer = MessageProducer()

    def consume(self):
        try:
            print(f"start consume: {self.topic}")

            while True:
                message = self.consumer.poll(1.0)
                if message is None:
                    continue
                if message.error():
                    print(f"Kafka error: {message.error()}")
                else:
                    self.handle_message(message)
        except KafkaException as e:
            self.logger.error(e)
        finally:
            self.consumer.close()

    def handle_message(self, message):
        try:
            request = json.loads(message.value().decode('utf-8'))

            self.logger.info(f"{message.topic()} | key: {message.key()} | value: {request}")
            
            # call_agent(request)

            # --- 파이프라인 실행에 필요한 필드만 추출 ---
            user_id   = request.get('user_id')   or request.get('userId')
            job_id    = request.get('job_id')    or request.get('jobId')
            file_path = request.get('file_path') or request.get('filePath')     # s3://, http(s)://, 로컬 zip/폴더 OK

            # 필수 값 검증
            missing = [k for k, v in {'userId': user_id, 'jobId': job_id, 'filePath': file_path}.items() if v in (None, '')]
            if missing:
                payload = {
                    "eventType": "SecurityFinished",
                    "userId": user_id,
                    "jobId": job_id,
                    "status": "FAIL_BAD_REQUEST",
                    "exitCode": 1,
                    "reason": f"missing fields: {', '.join(missing)}"
                }
                self.producer.send_message('agent-res', payload, headers=[('AGENT', 'SECU')])
                return

            # --- 단일 실행 파이프라인 호출 (중간 체크포인트/로그는 pipeline에서 처리) ---
            result = run_security_pipeline(
                user_id=user_id,
                job_id=job_id,
                file_path=file_path
            )
            # result에는 status, exitCode, projectKey, projectRootPath, projectRootName, outputsDir, checkpoints 포함

            # --- 결과 회신 (토픽/헤더는 기존 유지) ---
            payload = {
                "eventType": "SecurityFinished",
                "userId": user_id,
                "jobId": job_id,
                **result
            }
            self.producer.send_message('agent-res', payload, headers=[('AGENT', 'SECU')])

        except Exception as e:
            self.logger.exception(e)

if __name__ == '__main__':
    consumer = MessageConsumer()
    consumer.consume()