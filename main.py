import telebot
from telebot import types
from collections import Counter
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
connection = sqlite3.connect('bot.db', check_same_thread=False)
cursor = connection.cursor()

cart = {}

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
#         address TEXT,
#         time TEXT,
#         comment TEXT)''')
# 
# cursor.execute('''CREATE TABLE IF NOT EXISTS categories (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         name TEXT,
#         description TEXT,
#         photo TEXT)''')
# 
# cursor.execute('''CREATE TABLE IF NOT EXISTS items (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         category INTEGER,
#         name TEXT,
#         price REAL)''')
# 
# cursor.execute("INSERT INTO categories (name, description, photo) VALUES (?, ?, ?)", ("Тестовая категория", "Категория, созданная для теста", "assets/menu placeholder.png", ))
# cursor.execute("INSERT INTO items (category, name, price) VALUES (?, ?, ?)", (1, "Пицца", 100, ))
# cursor.execute("INSERT INTO items (category, name, price) VALUES (?, ?, ?)", (1, "Чай", 200, ))
# connection.commit()
db_lock = Lock()


def update_cart(user, order):
    if user in cart.keys():
        cart[user].append(order)
    else:
        cart[user] = [order]


def print_order_info(order_id, user_id=False):
    execute_db_operation("SELECT * FROM orders WHERE id = ?", (order_id,))
    id, user, text, type, address, time, comment = cursor.fetchone()
    order = ""
    sum = 0.0
    counter = Counter(eval(text))

    for element, count in counter.items():
        if count > 1:
            order += f"\n*[блюдо]* - {element[2]} ({element[3]} руб.) *[{count} штук]*"
            sum += element[3] * count
        else:
            order += f"\n*[блюдо]* - {element[2]} ({element[3]} руб.)"
            sum += float(element[3])
    order += f"\n*[стоимость заказа]:* {sum} руб."
    text = f"*Информация о заказе #{id}:*\n{order}\n\n*[тип]* - {type}"
    if address is not None:
        text += f"\n*[адрес]* - {address}"
    text += f"\n*[время]* - {time}\n*[комментарий]* - {comment}"

    if user_id is False:
        return text
    else:
        return user, text


def print_user_info(user_id):
    execute_db_operation("SELECT * FROM users WHERE id = ?", (user_id,))
    id, phone, username = cursor.fetchone()
    return f"*Информация о пользователе:*\n*[имя пользователя]* - @{username}\n*[телефон]* - {phone}"


def print_cart(user_id):
    counter = Counter(cart[user_id])
    order = "*Корзина:*"
    sum = 0.0
    for element, count in counter.items():
        if count > 1:
            order += f"\n[{element[3]} руб.] - {element[2]} *[{count} штук]*"
        else:
            order += f"\n[{element[3]} руб.] - {element[2]}"
    for item in cart[user_id]:
        sum += item[3]
    return f"{order}\n*Сумма заказа*: {sum} руб."


def get_admins_list(channel_id):
    admins = []
    for user in bot.get_chat_administrators(channel_id):
        admins.append(user.user.id)
    return admins


def execute_db_operation(operation, args=()):
    with db_lock:
        cursor.execute(operation, args)
        connection.commit()


@bot.message_handler(commands=['admin_message'])
def admin_message(message):
    chat_id = message.chat.id
    if chat_id in get_admins_list(channel_id):
        send_admin_message(channel_id)
        bot.send_message(chat_id, "Сообщение добавлено в канал")
    else:
        bot.send_message(message.chat.id, "Простите, я не понимаю вашего сообщения. Пожалуйста, воспользуйтесь предоставленными кнопками или нажмите /start.")
        execute_db_operation("SELECT * FROM users WHERE id=?", (chat_id,))
        id, phone, username = cursor.fetchone()
        contact_markup = telebot.types.InlineKeyboardMarkup()
        contact_markup.add(telebot.types.InlineKeyboardButton(text=f'Связаться с @{username}', url=f'https://t.me/{username}'))
        bot.send_message(channel_id, text=f"*Внимание!*\nПользователь @{username} ({phone}) совершил попытку получить доступ к админской панели. Вы знаете этого человека?", reply_markup=contact_markup, parse_mode="Markdown")


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
    user_id, order_info = print_order_info(order_id, user_id=True)
    send_order_to_channel(order_id, channel_id, ready=True)
    bot.send_message(user_id, f"Ваш заказ принят в работу!\n\n{order_info}", parse_mode="Markdown")
    show_hint(user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('refuse_'))
def handle_refuse_callback(call):
    order_id = call.data.split('_')[-1]
    bot.delete_message(call.message.chat.id, call.message.message_id)
    user_id, order_info = print_order_info(order_id, user_id=True)
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    bot.send_message(user_id, f"Ваш заказ отменен!\n\n{order_info}", parse_mode="Markdown")
    show_hint(user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('close_'))
def handle_close_callback(call):
    order_id = call.data.split('_')[-1]
    bot.delete_message(call.message.chat.id, call.message.message_id)
    user_id, order_info = print_order_info(order_id, user_id=True)
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    bot.send_message(channel_id, f"Заказ выполнен!{order_info}\n\n{print_user_info(user_id)}", parse_mode="Markdown")
    bot.send_message(user_id, f"Ваш заказ выполнен!\n\n{order_info}", parse_mode="Markdown")
    show_hint(user_id)


def send_order_to_channel(order_id, channel_id, ready=False):
    user_id, order_info = print_order_info(order_id, user_id=True)
    ready_markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    if ready is False:
        ready_markup.add(telebot.types.InlineKeyboardButton("Принять", callback_data=f"ready_{order_id}"), telebot.types.InlineKeyboardButton("Отказаться", callback_data=f"refuse_{order_id}"))
        bot.send_message(channel_id, f"{order_info}\n\n{print_user_info(user_id)}", reply_markup=ready_markup, parse_mode="Markdown")
    else:
        ready_markup.add(telebot.types.InlineKeyboardButton("Готово", callback_data=f"close_{order_id}"))
        bot.send_message(channel_id, f"Заказ принят в работу!{order_info}\n\n{print_user_info(user_id)}", reply_markup=ready_markup, parse_mode="Markdown")


def send_admin_message(channel_id):
    admin_markup = telebot.types.InlineKeyboardMarkup()
    admin_markup.add(telebot.types.InlineKeyboardButton("Админская панель", callback_data="admin"))
    to_pin = bot.send_message(channel_id, "Чтобы получить доступ к администрированию бота, нажмите на кнопку под этим сообщением", reply_markup=admin_markup).message_id
    bot.pin_chat_message(chat_id=channel_id, message_id=to_pin, disable_notification=True)


@bot.callback_query_handler(func=lambda call: call.data == 'admin')
def handle_admin_callback(call):
    chat_id = call.from_user.id
    bot.answer_callback_query(callback_query_id=call.id, text="Перейдите в бота, чтобы продолжить работу", show_alert=True)
    admin_markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    admin_markup.add(telebot.types.InlineKeyboardButton("Добавить категорию", callback_data="add_category"), telebot.types.InlineKeyboardButton("Удалить категорию", callback_data="remove_category"))
    bot.send_message(chat_id, "Изменение состава меню (только для сотрудников)", reply_markup=admin_markup)


@bot.callback_query_handler(func=lambda call: call.data == 'add_category')
def handle_add_category_callback(call):
    chat_id = call.from_user.id
    bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Введите название категории")
    bot.register_next_step_handler(call.message, create_category)


def create_category(message):
    chat_id = message.chat.id
    category = message.text
    execute_db_operation("INSERT INTO categories (name) VALUES (?)", (category,))
    bot.send_message(chat_id, "Введите краткое описание для этой категории", )
    execute_db_operation("SELECT id FROM categories WHERE name = ? ORDER BY id DESC LIMIT 1", (category,))
    category_id = cursor.fetchone()[0]
    bot.register_next_step_handler(message=message, callback=add_category_description, id=category_id)


def add_category_description(message, id):
    chat_id = message.chat.id
    description = message.text
    execute_db_operation("UPDATE categories SET description = ? WHERE id = ?", (description, id,))
    bot.send_message(chat_id, "Отправьте картинку, меню категории")
    bot.register_next_step_handler(message=message, callback=handle_category_picture, category_id=id)


@bot.message_handler(content_types=['photo'])
def handle_category_picture(message, category_id=None):
    if category_id:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_path = file_info.file_path
        downloaded_file = bot.download_file(file_path)
        with open(f'assets/category_{category_id}.jpg', 'wb') as new_file:
            new_file.write(downloaded_file)
            execute_db_operation("UPDATE categories SET photo = ? WHERE id = ?", (f'assets/category_{category_id}.jpg', category_id,))
        continue_markup = types.InlineKeyboardMarkup()
        continue_markup.add(types.InlineKeyboardButton('Закончить', callback_data='end_category'))
        bot.send_message(message.chat.id, "Фотография успешно сохранена.\nТеперькажите пункт меню и его цену череэ точку с запятой (Пример блюда;100.0)", reply_markup=continue_markup)
        bot.register_next_step_handler(message=message, callback=add_category_item, category_id=category_id)
    else:
        bot.send_message(message.chat.id, "Зачем мне это?")
        show_hint(message.chat.id)


def add_category_item(message, category_id):
    chat_id = message.chat.id
    item = message.text.split(';')

    if len(item) == 2:
        execute_db_operation("INSERT INTO items (category, name, price) VALUES (?, ?, ?)", (int(category_id), item[0], float(item[1])))
        continue_markup = types.InlineKeyboardMarkup()
        continue_markup.add(types.InlineKeyboardButton('Закончить', callback_data='end_category'))
        bot.send_message(chat_id, "Укажите пункт меню и его цену череэ точку с запятой (Пример блюда;100.0)", reply_markup=continue_markup)
        bot.register_next_step_handler(message=message, callback=add_category_item, category_id=category_id)
        return


@bot.callback_query_handler(func=lambda call: call.data == 'end_category')
def handle_end_items(call):
    chat_id = call.message.chat.id
    bot.send_message(chat_id, "Категория успешно создана")


@bot.callback_query_handler(func=lambda call: call.data == 'remove_category')
def handle_remove_category_callback(call):
    chat_id = call.from_user.id
    remove_markup = types.InlineKeyboardMarkup()
    execute_db_operation("SELECT id, name, description FROM categories ORDER BY name asc")
    categories = cursor.fetchall()
    for category in categories:
        remove_markup.add(types.InlineKeyboardButton(f'{category[1]} - {category[2]}', callback_data=f'delete_category_{category[0]}'))
    bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Выберите категорию, которую хотите удалить", reply_markup=remove_markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_category_'))
def handle_delete_category_callback(call):
    category_id = call.data.split('_')[-1]
    os.remove(f"assets/category_{category_id}.jpg")
    execute_db_operation("DELETE FROM categories WHERE id = ?", (category_id,))
    execute_db_operation("DELETE FROM items WHERE category = ?", (category_id,))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Категория #{category_id} удалена")
    show_hint(call.message.chat.id)


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
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('Сделать заказ', callback_data='make_order'), types.InlineKeyboardButton('Посмотреть свои заказы', callback_data='list_order'))
    bot.send_message(message.chat.id, "Выберите, хотите сделать", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ['make_order', 'list_order'])
def choose_action(call):
    if call.data == 'make_order':
        make_order(call.message)
    if call.data == 'list_order':
        show_orders(call.message.chat.id, call.message.message_id)


def show_orders(chat_id, message_id):
    execute_db_operation("SELECT id FROM orders WHERE user = ?", (chat_id,))
    user_orders = cursor.fetchall()

    if user_orders:
        orders_text = "**Ваши заказы:**\n"
        for order in user_orders:
            orders_text += f"{print_order_info(order[0])}\n\n"
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=orders_text, parse_mode="Markdown")
        show_hint(chat_id)
    else:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="У вас пока нет заказов.")
        show_hint(chat_id)


def make_order(message, is_redacted=False):
    chat_id = message.chat.id
    execute_db_operation("SELECT * FROM categories ORDER BY name asc")
    categories = cursor.fetchall()
    menu_markup = types.InlineKeyboardMarkup()
    menu_markup.add(telebot.types.InlineKeyboardButton('Завершить заказ', callback_data='finish'))

    for item in categories:
        id, name, description, photo = item
        menu_markup.add(types.InlineKeyboardButton(text=name, callback_data=f'category_{id}'))

    photo = open('assets/menu placeholder.png', 'rb')
    if is_redacted is False:
        bot.delete_message(chat_id, message.message_id)
    bot.send_photo(chat_id, photo, caption="Выберите пункт меню", reply_markup=menu_markup)
    # if chat_id in cart.keys():
    #     bot.send_photo(chat_id, photo, caption=f"Выберите пункт меню \n\n{str(print_cart(chat_id))}", parse_mode="Markdown", reply_markup=menu_markup)
    # else:
    #     bot.send_photo(chat_id, photo, caption="Выберите пункт меню", reply_markup=menu_markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('category_'))
def choose_category(call):
    chat_id = call.message.chat.id
    category_id = call.data.split('_')[-1]
    execute_db_operation("SELECT name, description, photo FROM categories WHERE id = ?", (category_id,))
    name, description, photo = cursor.fetchone()
    menu_markup = types.InlineKeyboardMarkup(row_width=1)
    menu_markup.add(telebot.types.InlineKeyboardButton('Назад к меню', callback_data='back'))
    execute_db_operation("SELECT * FROM items WHERE category = ?", (category_id,))
    items = cursor.fetchall()
    for item in items:
        if item[1] == int(category_id):
            menu_markup.add(telebot.types.InlineKeyboardButton(text=f'[{item[3]} руб.] - {item[2]}', callback_data=f'menu_item_{item[0]}'))
    photo = open(photo, 'rb')
    bot.delete_message(chat_id, call.message.message_id)
    bot.send_photo(chat_id, photo, caption=f"Категория: *{name}*\n{description}\n\nВыберите свой заказ", parse_mode="Markdown", reply_markup=menu_markup)
    # if chat_id in cart.keys():
    #     bot.send_photo(chat_id, photo, caption=f"Категория: *{name}*\n{description}\n\nВыберите свой заказ \n\n{str(print_cart(chat_id))}", parse_mode="Markdown", reply_markup=menu_markup)
    # else:
    #     bot.send_photo(chat_id, photo, caption=f"Категория: *{name}*\n{description}\n\nВыберите свой заказ", parse_mode="Markdown", reply_markup=menu_markup)


@bot.callback_query_handler(func=lambda call: call.data == 'back')
def back_to_menu(call):
    make_order(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_item_'))
def select_item(call):
    chat_id = call.message.chat.id
    item_id = call.data.split('_')[-1]
    execute_db_operation("SELECT * FROM items WHERE id = ?", (item_id,))
    # category, name, price
    order = cursor.fetchone()
    update_cart(chat_id, order)
    make_order(call.message)


@bot.callback_query_handler(func=lambda call: call.data == 'finish')
def handle_continue_choice(call):
    chat_id = call.message.chat.id
    if cart and cart[chat_id]:
        execute_db_operation("INSERT INTO orders (user, text) VALUES (?, ?)", (chat_id, str(cart[chat_id])))
        if chat_id in cart.keys():
            cart[chat_id] = []
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton('Самовывоз', callback_data='pickup'), types.InlineKeyboardButton('Доставка', callback_data='delivery'))
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Выберите способ получения заказа:", reply_markup=markup)
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(chat_id=call.message.chat.id, text="Вы ничего не заказали")
        show_hint(chat_id)


@bot.callback_query_handler(func=lambda call: call.data in ['pickup', 'delivery'])
def handle_delivery_choice(call):
    order_type = 'Самовывоз' if call.data == 'pickup' else 'Доставка'
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (call.message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET type = ? WHERE id = ?", (order_type, order_id))
    chat_id = call.message.chat.id

    if order_type == 'Самовывоз':
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Введите время, в которое хотите забрать заказ:")
        bot.register_next_step_handler(call.message, process_time)
    else:
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Введите адрес доставки:")
        bot.register_next_step_handler(call.message, process_delivery_address)


def process_delivery_address(message):
    address = message.text
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET address = ? WHERE id = ?", (address, order_id))
    bot.send_message(message.chat.id, "Введите время, в которое хотите забрать заказ:")
    bot.register_next_step_handler(message, process_time)


def process_time(message):
    time = message.text
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET time = ? WHERE id = ?", (time, order_id))
    bot.send_message(chat_id=message.chat.id, text="Введите комментарий к заказу (напишите нет, если не нужно)")
    bot.register_next_step_handler(message, final_order)


def final_order(message):
    comment = message.text
    execute_db_operation("SELECT id FROM orders WHERE user = ? ORDER BY id DESC LIMIT 1", (message.chat.id,))
    order_id = cursor.fetchone()[0]
    execute_db_operation("UPDATE orders SET comment = ? WHERE id = ?", (comment, order_id))
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(types.InlineKeyboardButton("Сохранить", callback_data=f'save_order_{order_id}'), types.InlineKeyboardButton("Редактировать", callback_data=f'edit_order_{order_id}'), types.InlineKeyboardButton("Отменить", callback_data=f'cancel_order_{order_id}'))
    bot.send_message(message.chat.id, f"Спасибо за заказ! Ваш выбор: \n\n{print_order_info(order_id)}", reply_markup=markup, parse_mode="Markdown")
    show_hint(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_order_'))
def edit_order(call):
    order_id = call.data.split('_')[-1]
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    make_order(message=call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('save_order_'))
def save_order(call):
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Ваш заказ принят!")
    order_id = call.data.split('_')[-1]
    send_order_to_channel(order_id, channel_id)
    show_hint(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_order_'))
def cancel_order(call):
    order_id = call.data.split('_')[-1]
    execute_db_operation("DELETE FROM orders WHERE id = ?", (order_id,))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Заказ успешно отменен.")
    show_hint(call.message.chat.id)


@bot.message_handler(func=lambda message: True)
def handle_unknown_message(message):
    bot.send_message(message.chat.id, "Простите, я не понимаю вашего сообщения. Пожалуйста, воспользуйтесь предоставленными кнопками.")


if __name__ == '__main__':
    print('Бот запущен')
    bot.infinity_polling()
