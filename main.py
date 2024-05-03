import telebot
from telebot import types
import sqlite3
from threading import Lock
import os


def load_tokens():
    env_vars = {}
    with open('.env', 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                env_vars[key] = value
    return env_vars


env_vars = load_tokens()
bot = telebot.TeleBot(env_vars.get("TOKEN"))
channel_id = env_vars.get("CHANNEL")
connection = sqlite3.connect('orders.db', check_same_thread=False)
cursor = connection.cursor()

# создание таблиц
# cursor.execute('''CREATE TABLE IF NOT EXISTS users (
#         id INTEGER PRIMARY KEY,
#         phone TEXT,
#         username TEXT)''')
#
# cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         user INTEGER,
#         text TEXT,
#         type TEXT,
#         address TEXT)''')
# connection.commit()
db_lock = Lock()


def execute_db_operation(operation, args=()):
    with db_lock:
        cursor.execute(operation, args)
        connection.commit()


@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    execute_db_operation("SELECT * FROM users WHERE id=?", (chat_id,))
    user = cursor.fetchone()
    bot.send_sticker(message.chat.id, "CAACAgIAAxkBAAEL-_5mKY_MLopzi-aw1GTR7pFLZgWtVAACVAADQbVWDGq3-McIjQH6NAQ")

    if not user:
        bot.send_message(chat_id, "Привет! Пожалуйста, предоставь свой номер телефона:")
        bot.register_next_step_handler(message, save_phone)
    else:
        bot.send_message(chat_id, "Привет снова!")
        show_menu(message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('ready_'))
def handle_ready_callback(call):
    order_id = call.data.split('_')[-1]
    bot.delete_message(call.message.chat.id, call.message.message_id)
    execute_db_operation("SELECT * FROM orders WHERE id = ?", (order_id,))
    order_info = cursor.fetchone()
    user_id = order_info[1]  # ID пользователя
    order_text = f"Заказ готов!\n\nИнформация о заказе:\n\nЗаказ - {order_info[2]}\nТип - {order_info[3]}\nАдрес - {order_info[4]}"
    bot.send_message(user_id, order_text)
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    show_hint(user_id)


def send_order_to_channel(order_id, channel_id):
    execute_db_operation("SELECT * FROM orders WHERE id = ?", (order_id,))
    order_info = cursor.fetchone()
    execute_db_operation("SELECT * FROM users WHERE id = ?", (order_info[1],))
    user_info = cursor.fetchone()
    order_text = f"Информация о заказе #{order_info[0]}:\n\nЗаказчик - @{user_info[2]}\nНомер телефона - {user_info[1]}\n\nЗаказ - {order_info[2]}\nТип - {order_info[3]}\nАдрес - {order_info[4]}"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Готово", callback_data=f"ready_{order_id}"))
    bot.send_message(channel_id, order_text, reply_markup=markup)


def save_phone(message):
    chat_id = message.chat.id
    phone_number = message.text

    if not phone_number.isdigit():
        bot.send_message(chat_id, "Пожалуйста, введите корректный номер телефона (только цифры)")
        bot.register_next_step_handler(message, save_phone)
        return

    username = message.from_user.username
    execute_db_operation("INSERT INTO users (id, phone, username) VALUES (?, ?, ?)", (chat_id, phone_number, username))
    show_menu(message)


def show_hint(chat_id):
    bot.send_message(chat_id, "Подсказка: нажмите /start, если хотите продолжить работу с ботом")


def show_menu(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('Сделать заказ', callback_data='make_order'), types.InlineKeyboardButton('Посмотреть свои заказы', callback_data='list_order'))
    bot.send_message(message.chat.id, "Выберите, хотите сделать", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ['make_order', 'list_order'])
def choose_action(call):
    chat_id = call.message.chat.id
    action = call.data

    if action == 'make_order':
        # если с картинкой
        photo = open('assets/menu placeholder.png', 'rb')
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_photo(chat_id, photo, caption="Ознакомьтесь с меню и введите ваш заказ:")
        # если без картинки
        # bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Введите ваш заказ:")
        bot.register_next_step_handler(call.message, process_order)
    if action == 'list_order':
        show_orders(call.message.chat.id, call.message.message_id)


def show_orders(chat_id, message_id=None):
    execute_db_operation("SELECT id, text, type, address FROM orders WHERE user = ?", (chat_id,))
    user_orders = cursor.fetchall()

    if user_orders:
        orders_text = "Ваши заказы:\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for order in user_orders:
            order_id, order_text, order_type, order_address = order
            button_text = f"{order_text} ({order_type})"
            if order_type == 'Доставка':
                button_text += f" - {order_address}"
            button = types.InlineKeyboardButton(button_text, callback_data=f'show_order_{order_id}')
            markup.add(button)
        if message_id:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=orders_text, reply_markup=markup)
        else:
            bot.send_message(chat_id, orders_text, reply_markup=markup)
    else:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="У вас пока нет заказов.")
        show_hint(chat_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('show_order_'))
def show_order(call):
    order_id = call.data.split('_')[-1]
    execute_db_operation("SELECT text, type, address FROM orders WHERE id = ?", (order_id,))
    order_info = cursor.fetchone()
    order_text, order_type, order_address = order_info
    text = f"Текст заказа: {order_text}\nТип заказа: {order_type}"
    if order_type == 'Доставка':
        text += f"\nАдрес доставки: {order_address}"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("Редактировать текст", callback_data=f'edit_text_{order_id}'))
    if order_type == 'Доставка':
        markup.add(types.InlineKeyboardButton("Редактировать адрес", callback_data=f'edit_address_{order_id}'))
    markup.add(types.InlineKeyboardButton("Отменить заказ", callback_data=f'cancel_order_{order_id}'))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_text_'))
def edit_text_order(call):
    order_id = call.data.split('_')[-1]
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Введите новый текст заказа:")

    @bot.message_handler(func=lambda message: True, content_types=['text'])
    def handle_new_text(message):
        if message.chat.id == call.message.chat.id:
            new_text = message.text
            execute_db_operation("UPDATE orders SET text = ? WHERE id = ?", (new_text, order_id))
            bot.send_message(chat_id=call.message.chat.id, text="Текст заказа успешно изменен.")
            show_hint(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_address_'))
def edit_address_order(call):
    order_id = call.data.split('_')[-1]
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Введите новый адрес доставки:")

    @bot.message_handler(func=lambda message: True, content_types=['text'])
    def handle_new_address(message):
        if message.chat.id == call.message.chat.id:
            new_address = message.text
            execute_db_operation("UPDATE orders SET address = ? WHERE id = ?", (new_address, order_id))
            bot.send_message(chat_id=call.message.chat.id, text="Адрес доставки успешно изменен.")
            show_hint(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_order_'))
def cancel_order(call):
    order_id = call.data.split('_')[-1]
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Заказ успешно отменен.")
    show_hint(call.message.chat.id)


def process_order(message):
    chat_id = message.chat.id
    order = message.text
    execute_db_operation("INSERT INTO orders (user, text) VALUES (?, ?)", (chat_id, order))
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('Самовывоз', callback_data='pickup'), types.InlineKeyboardButton('Доставка', callback_data='delivery'))
    bot.send_message(chat_id, "Выберите способ получения заказа:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ['pickup', 'delivery'])
def handle_delivery_choice(call):
    order_type = 'Самовывоз' if call.data == 'pickup' else 'Доставка'
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (call.message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET type = ? WHERE id = ?", (order_type, order_id))
    chat_id = call.message.chat.id

    if order_type == 'Самовывоз':
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Ваш заказ будет ожидать вас для самовывоза.")
        show_hint(chat_id)
        finalize_order(chat_id)
    else:
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Введите адрес доставки:")
        bot.register_next_step_handler(call.message, process_delivery_address)


def process_delivery_address(message):
    address = message.text
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET address = ? WHERE id = ?", (address, order_id))
    bot.send_message(message.chat.id, "Спасибо! Ваш заказ будет доставлен по указанному адресу.")
    show_hint(message.chat.id)
    finalize_order(message.chat.id)


def finalize_order(chat_id):
    execute_db_operation("SELECT * FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (chat_id,))
    order_info = cursor.fetchone()
    send_order_to_channel(order_info[0], channel_id)
    print(f"Пользователь совершил заказ: {order_info}")


# @bot.message_handler(func=lambda message: True)
# def handle_unknown_message(message):
#     bot.send_message(message.chat.id, "Простите, я не понимаю вашего сообщения. Пожалуйста, воспользуйтесь предоставленными кнопками.")


if __name__ == '__main__':
    print('Бот запущен')
    bot.infinity_polling()
