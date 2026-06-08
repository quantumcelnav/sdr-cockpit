"""Training module — adaptive SDR curriculum, dual-level content (beginner/expert)."""

import json
import os
import logging

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

LESSONS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'training', 'lessons.json')

training_bp = Blueprint('training', __name__)

_lessons_cache = None


def _load_lessons():
    global _lessons_cache
    if _lessons_cache is None:
        with open(LESSONS_PATH) as f:
            _lessons_cache = json.load(f)
    return _lessons_cache


@training_bp.route('/api/training/modules')
def api_modules():
    data = _load_lessons()
    modules = []
    for m in data['modules']:
        modules.append({
            'id':     m['id'],
            'title':  m['title'],
            'color':  m['color'],
            'lesson_count': len(m['lessons']),
            'lessons': [{'id': l['id'], 'title': l['title'], 'icon': l.get('icon', '')}
                        for l in m['lessons']],
        })
    return jsonify({'modules': modules})


@training_bp.route('/api/training/lesson/<lesson_id>')
def api_lesson(lesson_id):
    level = request.args.get('level', 'beginner')
    if level not in ('beginner', 'expert'):
        level = 'beginner'

    data = _load_lessons()
    for m in data['modules']:
        for lesson in m['lessons']:
            if lesson['id'] == lesson_id:
                sections = []
                for sec in lesson.get('sections', []):
                    content = sec.get(level) or sec.get('beginner', {})
                    sections.append({
                        'id':       sec['id'],
                        'title':    sec['title'],
                        'headline': content.get('headline', ''),
                        'body':     content.get('body', ''),
                        'key_point': content.get('key_point', ''),
                        'sdr_demo': sec.get('sdr_demo'),
                    })
                return jsonify({
                    'id':      lesson['id'],
                    'title':   lesson['title'],
                    'icon':    lesson.get('icon', ''),
                    'module_title': m['title'],
                    'module_color': m['color'],
                    'sections': sections,
                    'quiz':    lesson.get('quiz', []),
                    'sdr_demo': lesson.get('sdr_demo'),
                })
    return jsonify({'error': 'Lesson not found'}), 404


@training_bp.route('/api/training/quiz/check', methods=['POST'])
def api_quiz_check():
    """Check a quiz answer. Returns correct/incorrect + explanation."""
    d = request.json
    lesson_id = d.get('lesson_id')
    q_index   = d.get('q_index', 0)
    answer    = d.get('answer')
    level     = d.get('level', 'beginner')

    data = _load_lessons()
    for m in data['modules']:
        for lesson in m['lessons']:
            if lesson['id'] == lesson_id:
                quiz = lesson.get('quiz', [])
                if q_index >= len(quiz):
                    return jsonify({'error': 'Invalid question index'}), 400
                q = quiz[q_index]
                correct = (answer == q['answer'])
                explanation = q.get(f'explanation_{level}') or q.get('explanation', '')
                return jsonify({
                    'correct':     correct,
                    'correct_idx': q['answer'],
                    'explanation': explanation,
                })
    return jsonify({'error': 'Lesson not found'}), 404
