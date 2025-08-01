import xml.etree.ElementTree as ET

class XmlMapperAnalyzer:
    """
    MyBatis/iBatis의 XML 매퍼 파일을 파싱하여
    쿼리 ID와 SQL 구문을 추출합니다.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.queries = {}
        try:
            tree = ET.parse(self.file_path)
            self.root = tree.getroot()
            self._extract_queries()
        except Exception as e:
            print(f"⚠️ [XML Parse Warning] Failed to parse file: {self.file_path}\n    Reason: {e}")
            self.root = None

    def _extract_queries(self):
        if self.root is None:
            return

        namespace = self.root.get('namespace', '')
        if not namespace:
            return

        query_tags = ['select', 'insert', 'update', 'delete']
        for tag in query_tags:
            for query in self.root.findall(tag):
                query_id = query.get('id')
                if query_id:
                    # 정규화된 쿼리 ID (e.g., "sampleDAO.selectSample")
                    full_query_id = f"{namespace}.{query_id}"
                    # SQL 구문에서 불필요한 공백과 줄바꿈 정리
                    sql_text = ' '.join(query.text.strip().split()) if query.text else ""
                    self.queries[full_query_id] = sql_text

    def get_queries(self) -> dict:
        return self.queries