"""The work order's section 16 baseline: tiny keyword rules, first match wins.

Not shipped and not used for routing -- it exists to show whether the model classifier
buys anything over the obvious rules. Written before looking at classifier results.
"""
from __future__ import annotations
import re

COLOUR = r"(red|blue|green|yellow|orange|purple|pink|black|white|grey|gray|brown|gold|teal|dark|light|lighter|darker)"
THING = r"(asteroid|enem|ball|star|block|coin|rock|meteor|bad guy|monster|alien|they|them|thing)"

RULES = {
 "games": [
  ("change_thing_look", rf"{THING}.*({COLOUR}|bigger|smaller)"),
  ("change_thing_speed", rf"{THING}.*(fast|slow|speed)|(fast|slow|speed).*{THING}"),
  ("make_avoid_game", r"avoid|dodge"),
  ("make_catch_game", r"catch"),
  ("add_enemy", r"enem|chase|bad guy|monster"),
  ("add_collectible", r"coin|collect|gem"),
  ("add_score", r"score|points"),
  ("add_collision", r"collision|collide|touch|hit"),
  ("replace_player_sprite", r"picture|image|sprite|photo"),
  ("add_jump", r"jump|gravity"),
  ("change_controls", r"wasd|mouse|control|arrow keys"),
  ("player_moves_itself", r"(square|player).*(fall|bounce|by itself)"),
  ("add_moving_thing", rf"add .*{THING}|add .*square"),
  ("set_title", r"title|call (it|my game)|name"),
  ("change_background", r"back\s*g?round"),
  ("change_player_size", r"bigger|smaller|size|larger"),
  ("change_player_colour", COLOUR),
  ("change_player_speed", r"fast|slow|speed|quick"),
 ],
 "website": [
  ("add_image", r"picture|photo|image"),
  ("add_gallery", r"gallery"),
  ("add_button", r"button|counter|switch"),
  ("add_card", r"card"),
  ("add_section", r"section|page|part"),
  ("change_font_size", r"font|words.*(big|small)|text.*(big|small)|writing"),
  ("change_colours", COLOUR + r"|colou?r"),
  ("change_heading", r"title|headline|heading|my website"),
  ("change_text", r"change|say|rename"),
 ],
 "research": [
  ("biggest_change", r"changed the most|grew the most|most"),
  ("scatter_plot", r"scatter"),
  ("line_chart", r"line"),
  ("histogram", r"histogram|spread"),
  ("bar_chart", r"bar"),
  ("group_average", r"average|mean"),
  ("group_count", r"how many|count"),
  ("filter_rows", r"only|filter|find the"),
  ("describe_data", r"what'?s in|describe|summar"),
 ],
 "arduino": [
  ("make_traffic_light", r"traffic"),
  ("add_servo", r"servo|motor"),
  ("read_sensor", r"sensor|potentiometer"),
  ("add_button", r"button"),
  ("add_led", r"\bled\b"),
  ("add_serial_message", r"serial|print"),
  ("change_blink_pattern", r"pattern|heartbeat|sos|double"),
  ("change_blink_speed", r"fast|slow|blink|longer|shorter|millisecond|second"),
 ],
 "raspberry_pi": [
  ("add_motor", r"servo|motor"),
  ("read_sensor", r"sensor"),
  ("add_button", r"button"),
  ("change_led_pin", r"\bpin\b"),
  ("blink_forever", r"forever|keep blinking|never stop"),
  ("change_blink_count", r"\d+ times|times"),
  ("change_blink_speed", r"fast|slow|longer|shorter|second|gap"),
 ],
}

def classify(profile: str, text: str) -> str:
    lowered = text.lower()
    for intent, pattern in RULES.get(profile, []):
        if re.search(pattern, lowered):
            return intent
    return "other"
