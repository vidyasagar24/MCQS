import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

// Custom metric for failure rate
const errorRate = new Rate('error_rate');

export const options = {
  stages: [
    { duration: '30s', target: 50 },   // Warm-up to 50 concurrent students
    { duration: '1m',  target: 250 },  // Scale up to 250 concurrent students
    { duration: '2m',  target: 500 },  // Peak load: 500 simultaneous students
    { duration: '1m',  target: 500 },  // Sustained peak at 500 users
    { duration: '30s', target: 0 },    // Ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(95)<2500'], // 95% of requests must complete within 2.5s
    'error_rate': ['rate<0.02'],        // Error rate must remain below 2%
  },
};

const BASE_URL = __ENV.TARGET_URL || 'http://127.0.0.1:5000';
const QUIZ_CODE = __ENV.QUIZ_CODE || 'MATH2026';

export default function () {
  // Generate student SAP ID between 2026CE001 and 2026CE082
  const studentNum = ((__VU * 7 + __ITER) % 82) + 1;
  const sapId = `2026CE${String(studentNum).padStart(3, '0')}`;
  const studentEmail = `${sapId.toLowerCase()}@institution.edu`;

  const headers = { 'Content-Type': 'application/json' };

  // 1. Verify Student
  const verifyRes = http.post(
    `${BASE_URL}/api/mq/verify-student`,
    JSON.stringify({
      student_name: `Student ${sapId}`,
      sap_id: sapId,
      email: studentEmail,
      quiz_code: QUIZ_CODE
    }),
    { headers: headers }
  );

  const verifySuccess = check(verifyRes, {
    'verify status is 200': (r) => r.status === 200,
    'student verified': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.success === true;
      } catch (e) {
        return false;
      }
    },
  });
  errorRate.add(!verifySuccess);

  if (!verifySuccess) {
    sleep(1);
    return;
  }

  const verifyData = JSON.parse(verifyRes.body).data;
  const quizId = verifyData.quiz_id;
  const studentId = verifyData.student_id;

  // 2. Start / Resume Examination Attempt
  const startRes = http.post(
    `${BASE_URL}/api/mq/start-attempt`,
    JSON.stringify({
      quiz_id: quizId,
      student_id: studentId
    }),
    { headers: headers }
  );

  const startSuccess = check(startRes, {
    'start_attempt status is 200': (r) => r.status === 200,
  });
  errorRate.add(!startSuccess);

  if (!startSuccess) {
    sleep(1);
    return;
  }

  const sessionToken = JSON.parse(startRes.body).data.session_token;

  // 3. Retrieve Assigned Question Paper
  const paperRes = http.post(
    `${BASE_URL}/api/mq/get-paper`,
    JSON.stringify({ session_token: sessionToken }),
    { headers: headers }
  );

  const paperSuccess = check(paperRes, {
    'paper status is 200': (r) => r.status === 200,
    'questions assigned': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.paper && body.paper.questions && body.paper.questions.length > 0;
      } catch (e) {
        return false;
      }
    },
  });
  errorRate.add(!paperSuccess);

  if (!paperSuccess) {
    sleep(1);
    return;
  }

  const questions = JSON.parse(paperRes.body).paper.questions;

  // 4. Answer Saving Loop (Candidate answering questions during exam)
  const optionsList = ['A', 'B', 'C', 'D'];
  for (let i = 0; i < Math.min(questions.length, 5); i++) {
    const q = questions[i];
    const chosenOption = optionsList[(i + __VU) % 4];
    const idempotencyKey = `idem-${sessionToken.substring(0, 8)}-${q.id}-${i}`;

    const saveRes = http.post(
      `${BASE_URL}/api/mq/save-answer`,
      JSON.stringify({
        session_token: sessionToken,
        question_id: q.id,
        selected_option: chosenOption,
        idempotency_key: idempotencyKey
      }),
      { headers: headers }
    );

    const saveSuccess = check(saveRes, {
      'save_answer status is 200': (r) => r.status === 200,
    });
    errorRate.add(!saveSuccess);

    // Realistic thinking pause between answers
    sleep(0.5);
  }

  // 5. Submit Examination Attempt
  const submitRes = http.post(
    `${BASE_URL}/api/mq/submit-attempt`,
    JSON.stringify({
      session_token: sessionToken,
      auto: false,
      reason: 'Candidate completed examination'
    }),
    { headers: headers }
  );

  const submitSuccess = check(submitRes, {
    'submit status is 200': (r) => r.status === 200,
  });
  errorRate.add(!submitSuccess);

  // 6. Check Results (Should respect Admin Gate)
  const resultRes = http.post(
    `${BASE_URL}/api/mq/check-result`,
    JSON.stringify({
      sap_id: sapId,
      email: studentEmail,
      quiz_code: QUIZ_CODE
    }),
    { headers: headers }
  );

  const resultSuccess = check(resultRes, {
    'check_result status is 200': (r) => r.status === 200,
  });
  errorRate.add(!resultSuccess);

  sleep(1);
}
