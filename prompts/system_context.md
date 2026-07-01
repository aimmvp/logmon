## 1. 개요

- 이 시스템은 Swing 서비스의 로그인을 담당한다.

## 2. SSO 정책서버 구성

- OS Kernel : Linux 4.18.0
- SSO : Symantec Siteminder 12.80
- JDK : Java version “1.8.0_345” (64bit)
- Tomcat : 7.0.100
- Spring Framework : 3.2.17.RELEASE

## 3. SSO 프로세스 구동

### 3-1. 서비스 중지

- Home Directory: /appsw/siteminder/CA/siteminder
- command : ./stop.sh

### 3-2. 서비스 구동

- Home Directory: /appsw/siteminder/CA/siteminder
- command : ./start.sh

### 3-3. 프로세스(smpolicysrv) 확인

- command : ps -ef | grep smpolicysrv

## 4. SSO Log

### 4-1. 개요 : SSO 로그는 SSO 정책서버 상태 확인 로그(smps.log), Siteminder의 API를 Customizing 한 Library 로그( swg_lib.log), Tomcat 에 올라가 있는 Java 영역의 로그(catalina.out)로 구성된다.

### 4-2. 공통점

- Directory : /applog/smuser/sso/
- 보관기간 : 90일(Rolling)

### 4-3. SSO 정책 서버 상태 확인 로그

- 서버 상태는 1분 단위로 기록하고 있음
- 파일명 : smps.log
- sample : [Tue Jun 23 2026 22:31:02] Msgs=1000250 Throughput=1.968628 Response_Time=4.403502 Wait_Time_In_Queue=0.005269 Max_HP_Msg=6 Max_NP_Msg=6 Current_Depth=0 Max_Depth=7 Current_High_Depth=0 Current_Norm_Depth=0 Current_Threads=8 Max_Threads=8 Busy_Threads=0 Current_Connections=38 Max_Connections=435 Exceeded_Limit=0 Core_Result=N]
    - 각 항목의 의미는 Siteminder 공식문서 참고

### 4-4. Swing Library 로그

- Siteminder 의 API를 Customizing한 Library 로그이며, 주로 1차인증(ID/PWD) 에 관여함
- 파일명 : swing_auth.log
- sample log : 20260623223754,AuthType=PWD,AuthResult=0,AuthReason=32000,ID=D23807129,STATUS=0,CO_CL_CD=T
- 1차 인증
    - 시도 : AuthType=PWD
    - 성공 : AuthType=PWD, AuthResult=0
    - 실패 : AuthType=PWD, AuthResult=-1
- 1차인증은 5회까지 허용되며, 5회 연속 실패 시 잠금상태로 변경됨. 따라서 연속 6회 실패했을 경우 이상동작으로 판단 가능

### 4-5. Tomcat 로그

- tomcat 에 올라가 있는 java 영역의 로그로 주로 2차 인증 관련 로그가 있음
- 파일명 : catalina.out
- 2차인증 Otp 를 generate/send 하는 sendotppwd 와 otp 의 mq를 이용한 실제 발송을 위한 sendsmsbymqput 으로 구성됨
- 2차 인증
    - OTP 발송시도 : catalina log 에서 message 에 "Request OTP Generate" 가 포함된 로그
    - OTP 인증성공 : catalina log 에서 message 에 "Verification result = [true]" 가 포함된 로그
    - OTP 인증실패 : catalina log 에서 message 에 "Verification result = [false]" 가 포함된 로그

## 5. 알람 대상(manual)

- 모든 수치는 기본적으로 지난주 같은 요일의 비슷한 시간대 값을 비교 대상으로 한다.

### 5-1. 즉시 조치 필요 기준

- BusyThread < 0
- BusyThread > 100
- 각 항목의 임계치와 20% 이상 차이가 난다.