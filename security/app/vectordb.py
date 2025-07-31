'''
verctor DB 생성
'''
from langchain.document_loaders import PyMuPDFLoader
import fitz

path = r"C:\Users\User\Downloads\표준프레임워크_보안개발_가이드(2024.02).pdf"

pdf_loader = PyMuPDFLoader(path)
pdf_data = pdf_loader.load()
print(len(pdf_data))
print(pdf_data[9])

doc = fitz.open(path)
print(doc[9].get_text())