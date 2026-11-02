"""테스트 실행기: 테스트 중에는 실제 LLM 호출과 네트워크 연결을 막는다.

.env에 진짜 LLM_API_KEY가 있어도 테스트가 바깥으로 요청을 보내지 않게 한다.
- advisor.llm._send(LLM으로 나가는 유일한 길)를 막는다. 가짜 답이 필요한 테스트는 mock.patch로 잠시 바꿔 쓴다.
- 혹시 다른 길이 생겨도 소켓 연결 자체를 막아서, 실제 연결을 시도하면 그 테스트가 실패한다.
"""

import socket

from django.test.runner import DiscoverRunner


class RealNetworkCallInTest(AssertionError):
    pass


def _blocked_send(*args, **kwargs):
    raise RealNetworkCallInTest("테스트 중에 실제 LLM 호출을 시도했어요. advisor.llm._send를 mock으로 바꿔 주세요.")


def _blocked_connect(self, *args, **kwargs):
    raise RealNetworkCallInTest("테스트 중에 실제 네트워크 연결을 시도했어요.")


class NoNetworkTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from advisor import llm

        self._saved = (llm._send, socket.socket.connect, socket.socket.connect_ex)
        llm._send = _blocked_send
        socket.socket.connect = _blocked_connect
        socket.socket.connect_ex = _blocked_connect

    def teardown_test_environment(self, **kwargs):
        from advisor import llm

        llm._send, socket.socket.connect, socket.socket.connect_ex = self._saved
        super().teardown_test_environment(**kwargs)
