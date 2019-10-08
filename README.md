# pypbac
Power BI Athena Connector in Python

## 소개

마이크로소프트의 Power BI에서 AWS Athena 데이터를 불러오기 위한 커넥터입니다. 

## 설치 방법

1. 압축 파일을 적당한 디렉토리에 풉니다.
2. 디렉토리내 `python.exe`를 실행합니다.
3. 최초 한 번 AWS 계정 설정을 해줍니다.
4. 입력한 AWS 계정 정보로 접속에 성공하면, DB를 선택할 수 있습니다.

## 불러오기 설정하기
1. 먼저 불러올 대상 시간을 지정합니다. `상대 시간`과 `절대 시간`으로 나뉩니다.
  1. 상대적인 시간 - 몇 일전부터 몇 일치를 불러올지 지정
  2. 절대 시간 - 구체적인 시작/종료 날자를 지정
2. 다음으로 DB를 선택합니다. DB가 선택되면, 거기에 있는 테이블 리스트가 나옵니다.
3. Power BI에서 불러올 테이블들을 체크합니다.
4. `저장 후 종료` 버튼을 눌러 설정을 저장하고 종료합니다.

## Power BI에서 설정하기
1. Power BI `옵션 및 설정` 메뉴의 `옵션`을 선택합니다.
2. 옵션 대화창에서 `Python 스크립팅`을 선택합니다.
3. `검색된 Python 홈 디렉터리` 란에서 `기타`를 선택합니다.
3. `Python 홈 디렉토리를 설정합니다.`란에서 `찾아보기`를 누릅니다.
4. 설치 단계에서 압축을 푼 디렉토리를 지정합니다.
5. `확인`을 누릅니다.

## Power BI에서 불러오기
1. `홈` 리본에 `데이터 가져오기`를 선택합니다.
2. 메뉴에서 `추가...`를 선택합니다.
3. `데이터 가져오기` 대화창의 입력란에서 `python`을 입력합니다.
4. `Python 스크립트`를 선택후, `연결`을 누릅니다.
5. 이어 나오는 대화창에서 `스크립트`는 공란을 허용하지 않기에, 아무 문자나 입력합니다.
6. `확인`을 누르면 연결이 시작되고, 데이터를 가져옵니다.
7. 지정된 시간 범위나 테이블의 크기에 따라 다양한 시간이 소요됩니다.


## 추가 설명
- Power BI는 *불명한 이유로 파이썬 데이터 가져오기를 여러번 수행*합니다.
- 이에 대처하기 위해 pypbac는 로컬 디스크에 데이터를 **캐쉬**로서 저장합니다.
- 한 번 저장된 데이터는 로컬 캐쉬에서 빠르게 불러올 수 있습니다.
- 다음과 같은 경우 캐쉬는 무효화 되고, 다음 불러오기를 할 때 새로 가져오게 됩니다.
  - 생성된 이후 `로컬 캐쉬 유효 시간` 보다 오래된 경우
  - pypbac의 설정 파일이 변경된 경우
